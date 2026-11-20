"""Study sheets written from uploaded materials (smart tier), with their sources."""

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class StudySheet(CreatedAtMixin, Base):
    __tablename__ = "study_sheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    week_no: Mapped[int | None]
    title: Mapped[str] = mapped_column(String(300))
    content_md: Mapped[str] = mapped_column(Text)  # ends with the "Kaynaklar" list
    # [{"n": 1, "title": "ee211_notlar.pdf", "pages": "s. 4", "material_id": 3}]
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(100))  # provider/model that wrote it
