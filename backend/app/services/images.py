"""Images sent in the chat: validated, re-encoded without metadata, scaled down, stored.

- HEIC/HEIF (iPhone) -> JPEG; photos -> JPEG; PNG (screenshots, crisp text) stays PNG.
- EXIF (camera, GPS location, ...) is never kept: the pixels are copied into a fresh image,
  after the EXIF orientation has been applied to them.
- Longer side scaled down to IMAGE_MAX_EDGE (1600 px): enough for a model to read a
  timetable, small enough to keep vision tokens cheap.
"""

import datetime as dt
import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

# A 1600 px image never needs a source this large; bigger ones are refused before decoding
# (decompression bombs), instead of Pillow's warning.
MAX_SOURCE_PIXELS = 60_000_000
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "GIF", "MPO", "BMP"}
JPEG_QUALITY = 85


class ImageError(ValueError):
    """The upload is not an image we accept. `code` is shown to the user (i18n)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    data: bytes
    mime: str
    extension: str
    width: int
    height: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def process_image(raw: bytes, *, max_bytes: int, max_edge: int) -> ProcessedImage:
    if len(raw) > max_bytes:
        raise ImageError("too_large", f"{len(raw)} bytes > {max_bytes}")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            source_format = probe.format or ""
            if probe.width * probe.height > MAX_SOURCE_PIXELS:
                raise ImageError("too_many_pixels", f"{probe.width}x{probe.height}")
            if source_format not in ACCEPTED_FORMATS:
                raise ImageError("unsupported", source_format)
            probe.seek(0)  # animated GIF / multi-frame HEIC: the first frame
            image = ImageOps.exif_transpose(probe)  # rotate as shot, before EXIF is dropped
            image.load()
    except ImageError:
        raise
    except Exception as exc:  # Pillow raises many types for broken / non-image data
        raise ImageError("not_an_image", str(exc)) from exc

    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    keep_png = source_format == "PNG"
    if keep_png:
        mode = "RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB"
        image = image.convert(mode)
    else:
        image = _flatten(image)
    clean = Image.new(image.mode, image.size)  # pixels only: no EXIF, XMP, ICC, text chunks
    clean.paste(image)

    out = io.BytesIO()
    if keep_png:
        clean.save(out, format="PNG", optimize=True)
        mime, extension = "image/png", "png"
    else:
        clean.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        mime, extension = "image/jpeg", "jpg"
    return ProcessedImage(out.getvalue(), mime, extension, clean.width, clean.height)


def _flatten(image: Image.Image) -> Image.Image:
    """RGB for JPEG: transparency onto white."""
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def store_image(image: ProcessedImage, upload_dir: Path, now: dt.datetime) -> str:
    """Writes the file under upload_dir/YYYY/MM/ and returns its relative path."""
    relative = Path(f"{now:%Y}") / f"{now:%m}" / f"{uuid.uuid4().hex}.{image.extension}"
    target = upload_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(image.data)
    return relative.as_posix()


def resolve_stored(upload_dir: Path, relative: str) -> Path:
    """The file of a stored path; refuses anything outside upload_dir."""
    base = upload_dir.resolve()
    target = (base / relative).resolve()
    if base not in target.parents:
        raise ImageError("not_found", relative)
    return target
