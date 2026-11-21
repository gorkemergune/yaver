"""Course materials (Phase 3): uploaded PDFs / photos, their text in chunks with embeddings
(pgvector) for `search_materials`, and the weekly topics read from a syllabus."""

import datetime as dt

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin

EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2 (app/rag/embed.py)


class CourseMaterial(TimestampMixin, Base):
    __tablename__ = "course_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20))  # syllabus | notes | slides | other
    title: Mapped[str] = mapped_column(String(300))  # the file name, for citations
    pages: Mapped[int]
    week_no: Mapped[int | None]  # term week the notes belong to (None: whole course)
    indexed_at: Mapped[dt.datetime | None]  # chunks + embeddings written (None: pending)
    source_text: Mapped[str | None] = mapped_column(Text)  # a photo's text (PDFs: the file)


class MaterialChunk(Base):
    """A passage of a material with the pages it comes from (for "dosya + sayfa")."""

    __tablename__ = "material_chunks"
    __table_args__ = (
        Index(
            "ix_material_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("course_materials.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[int | None] = mapped_column(index=True)  # copied for filtering
    week_no: Mapped[int | None]
    page_start: Mapped[int]
    page_end: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class SyllabusWeek(CreatedAtMixin, Base):
    __tablename__ = "syllabus_weeks"
    __table_args__ = (
        UniqueConstraint("course_id", "week_no", name="uq_syllabus_weeks_course_week"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    material_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_materials.id", ondelete="SET NULL")
    )
    week_no: Mapped[int]
    topics: Mapped[str] = mapped_column(Text)
    # From a full syllabus import (app.materials.ingest); None when the syllabus says nothing.
    dates_text: Mapped[str | None] = mapped_column(String(80))  # as written ("5-9 Ekim")
    readings: Mapped[str | None] = mapped_column(Text)  # book sections / texts to read
    lab: Mapped[str | None] = mapped_column(Text)  # the week's lab / lab assignment
    assessment: Mapped[str | None] = mapped_column(Text)  # exam, quiz, deadline that week


class CourseBook(CreatedAtMixin, Base):
    """A textbook a syllabus names; `material_id` once its PDF is in the materials."""

    __tablename__ = "course_books"
    __table_args__ = (UniqueConstraint("course_id", "title", name="uq_course_books_course_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    authors: Mapped[str | None] = mapped_column(String(300))
    edition: Mapped[str | None] = mapped_column(String(60))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    material_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_materials.id", ondelete="SET NULL")
    )


class MaterialSection(Base):
    """A chapter / section / experiment of a material (its table of contents) with its
    pages and the term weeks it belongs to ("4.e Experiment #5", s. 40-43, weeks [9])."""

    __tablename__ = "material_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("course_materials.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[int | None] = mapped_column(index=True)  # copied for filtering
    number: Mapped[str | None] = mapped_column(String(20))  # "1.3", "4.e"
    title: Mapped[str] = mapped_column(String(300))
    page_start: Mapped[int]  # PDF pages, 1-based
    page_end: Mapped[int]
    week_nos: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list, server_default="{}")
