"""Image and PDF uploads for the chat: POST the files first, then send the message with
their ids. Images are re-encoded; PDFs are kept as they are (read in agent.documents)."""

import asyncio
import datetime as dt
import hashlib
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Attachment
from app.db.session import get_session
from app.rag.pdf import is_pdf
from app.services.images import ImageError, process_image, resolve_stored, store_image

router = APIRouter(tags=["uploads"])

MAX_FILES = 6
_STATUS = {"too_large": 413, "too_many_pixels": 413}


def attachment_view(attachment: Attachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "url": f"/api/uploads/{attachment.id}",
        "mime": attachment.mime,
        "width": attachment.width,
        "height": attachment.height,
        "filename": attachment.filename,
    }


def safe_name(name: str | None, fallback: str) -> str:
    """The uploaded file name for display / citations: no path, no control characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f]", "", base).strip()
    return base[:200] or fallback


def store_pdf(raw: bytes, upload_dir: Path, now: dt.datetime) -> str:
    """uploads/YYYY/MM/<sha256>.pdf (same layout as images); returns the relative path."""
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"{now:%Y/%m}/{digest}.pdf"
    target = upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(raw)
    return relative


@router.post("/uploads")
async def upload_images(
    files: Annotated[list[UploadFile], File(description="images (JPEG, PNG, HEIC, WebP...), PDFs")],
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(422, detail={"code": "no_files"})
    if len(files) > MAX_FILES:
        raise HTTPException(422, detail={"code": "too_many_files", "max": MAX_FILES})
    max_bytes = int(settings.upload_max_mb * 1024 * 1024)
    stored: list[Attachment] = []
    for upload in files:
        raw = await upload.read(max_bytes + 1)  # one byte over the limit is enough to refuse
        if is_pdf(raw):
            if len(raw) > max_bytes:
                raise HTTPException(413, detail={"code": "too_large", "file": upload.filename})
            now = dt.datetime.now(dt.UTC)
            pdf_path = await asyncio.to_thread(store_pdf, raw, settings.upload_dir, now)
            pdf = Attachment(
                path=pdf_path,
                mime="application/pdf",
                width=0,
                height=0,
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                filename=safe_name(upload.filename, "belge.pdf"),
            )
            session.add(pdf)
            stored.append(pdf)
            continue
        try:
            image = await asyncio.to_thread(
                process_image, raw, max_bytes=max_bytes, max_edge=settings.image_max_edge
            )
        except ImageError as exc:
            raise HTTPException(
                _STATUS.get(exc.code, 415), detail={"code": exc.code, "file": upload.filename}
            ) from exc
        path = await asyncio.to_thread(
            store_image, image, settings.upload_dir, dt.datetime.now(dt.UTC)
        )
        attachment = Attachment(
            path=path,
            mime=image.mime,
            width=image.width,
            height=image.height,
            size_bytes=len(image.data),
            sha256=image.sha256,
            filename=safe_name(upload.filename, "görsel.jpg"),
        )
        session.add(attachment)
        stored.append(attachment)
    await session.commit()
    return {"attachments": [attachment_view(a) for a in stored]}


@router.get("/uploads/{attachment_id}")
async def get_image(
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    attachment = await session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(404)
    try:
        path = resolve_stored(settings.upload_dir, attachment.path)
    except ImageError as exc:
        raise HTTPException(404) from exc
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(
        path,
        media_type=attachment.mime,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
