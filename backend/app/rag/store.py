"""Writes a material's passages with embeddings and searches them (cosine, pgvector)."""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Course, CourseMaterial, MaterialChunk
from app.rag.chunk import chunk_pages
from app.rag.embed import Embedder, embed


async def index_material(
    session: AsyncSession,
    material: CourseMaterial,
    pages: list[str],
    now: dt.datetime,
    embedder: Embedder | None = None,
) -> int:
    """(Re)writes the material's chunks; returns how many. Course / week are copied onto
    the chunks so a search can filter without a join."""
    await session.execute(delete(MaterialChunk).where(MaterialChunk.material_id == material.id))
    chunks = chunk_pages(pages)
    vectors = await embed([c.content for c in chunks], embedder)
    for chunk, vector in zip(chunks, vectors, strict=True):
        session.add(
            MaterialChunk(
                material_id=material.id,
                course_id=material.course_id,
                week_no=material.week_no,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                content=chunk.content,
                embedding=vector,
            )
        )
    material.indexed_at = now
    await session.flush()
    return len(chunks)


@dataclass(frozen=True, slots=True)
class Hit:
    material_id: int
    title: str
    kind: str
    course: str | None
    week_no: int | None
    page_start: int
    page_end: int
    content: str
    score: float  # cosine similarity, 1 = same meaning

    @property
    def pages(self) -> str:
        if self.page_start == self.page_end:
            return f"s. {self.page_start}"
        return f"s. {self.page_start}-{self.page_end}"


async def search(
    session: AsyncSession,
    query: str,
    *,
    course_id: int | None = None,
    week_no: int | None = None,
    limit: int = 5,
    embedder: Embedder | None = None,
    material_ids: list[int] | None = None,
) -> list[Hit]:
    [vector] = await embed([query], embedder)
    distance = MaterialChunk.embedding.cosine_distance(vector)
    statement = (
        select(MaterialChunk, CourseMaterial, Course.code, distance.label("distance"))
        .join(CourseMaterial, CourseMaterial.id == MaterialChunk.material_id)
        .outerjoin(Course, Course.id == MaterialChunk.course_id)
        .order_by(distance)
        .limit(limit)
    )
    if course_id is not None:
        statement = statement.where(MaterialChunk.course_id == course_id)
    if week_no is not None:
        statement = statement.where(MaterialChunk.week_no == week_no)
    if material_ids is not None:
        statement = statement.where(MaterialChunk.material_id.in_(material_ids))
    rows = (await session.execute(statement)).all()
    return [
        Hit(
            material_id=material.id,
            title=material.title,
            kind=material.kind,
            course=code,
            week_no=chunk.week_no,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            content=chunk.content,
            score=round(1 - float(dist), 3),
        )
        for chunk, material, code, dist in rows
    ]
