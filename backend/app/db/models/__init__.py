"""ORM models. Import every model module here so Alembic autogenerate sees it."""

from app.db.models.academic import Course, Holiday, Term

__all__ = ["Course", "Holiday", "Term"]
