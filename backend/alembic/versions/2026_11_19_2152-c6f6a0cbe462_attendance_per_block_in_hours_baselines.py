"""attendance per block in hours, baselines

Day-based rows (course, date) become one row per class block of that day, with the block's
class hours; rows whose day has no matching block keep recurring_block_id NULL, 1 hour.

Revision ID: c6f6a0cbe462
Revises: d5aa7d7dd829
Create Date: 2026-11-19 21:52:21.333326+00:00

"""
from typing import Sequence, Union

import datetime as dt

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c6f6a0cbe462'
down_revision: Union[str, Sequence[str], None] = 'd5aa7d7dd829'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BLOCKS_OF_THE_DAY = sa.text(
    """
    SELECT b.id, b.start_time, b.end_time
    FROM recurring_blocks b
    WHERE b.course_id = :course AND b.weekday = :weekday
      AND (b.valid_from IS NULL OR b.valid_from <= :day)
      AND (b.valid_to IS NULL OR b.valid_to >= :day)
      AND NOT EXISTS (
          SELECT 1 FROM block_overrides o WHERE o.block_id = b.id AND o.date = :day
      )
    ORDER BY b.start_time
    """
)


def class_hours(start: dt.time, end: dt.time) -> int:
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if minutes <= 0:
        minutes += 24 * 60  # ends after midnight
    return max(1, round(minutes / 60))


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "attendance_baselines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("hours", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("hours >= 0", name=op.f("ck_attendance_baselines_hours_not_negative")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name=op.f("fk_attendance_baselines_course_id_courses"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance_baselines")),
        sa.UniqueConstraint("course_id", name=op.f("uq_attendance_baselines_course_id")),
    )
    op.add_column("attendance", sa.Column("recurring_block_id", sa.Integer(), nullable=True))
    op.add_column("attendance", sa.Column("hours", sa.Integer(), server_default="1", nullable=False))
    op.drop_constraint(op.f("uq_attendance_course_date"), "attendance", type_="unique")

    # data: one row per block of that day (skipped / moved occurrences are not sessions)
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, course_id, date, status, note, created_at, updated_at "
            "FROM attendance ORDER BY id"
        )
    ).mappings().all()
    for row in rows:
        blocks = conn.execute(
            BLOCKS_OF_THE_DAY,
            {"course": row["course_id"], "weekday": row["date"].weekday(), "day": row["date"]},
        ).all()
        if not blocks:
            continue
        first, *rest = blocks
        conn.execute(
            sa.text("UPDATE attendance SET recurring_block_id = :block, hours = :hours WHERE id = :id"),
            {"block": first.id, "hours": class_hours(first.start_time, first.end_time), "id": row["id"]},
        )
        for block in rest:
            conn.execute(
                sa.text(
                    "INSERT INTO attendance (course_id, date, recurring_block_id, hours, status, "
                    "note, created_at, updated_at) VALUES (:course, :day, :block, :hours, "
                    ":status, :note, :created, :updated)"
                ),
                {
                    "course": row["course_id"],
                    "day": row["date"],
                    "block": block.id,
                    "hours": class_hours(block.start_time, block.end_time),
                    "status": row["status"],
                    "note": row["note"],
                    "created": row["created_at"],
                    "updated": row["updated_at"],
                },
            )

    op.create_index(op.f("ix_attendance_recurring_block_id"), "attendance", ["recurring_block_id"], unique=False)
    op.create_unique_constraint(
        op.f("uq_attendance_course_date_block"), "attendance", ["course_id", "date", "recurring_block_id"]
    )
    op.create_foreign_key(
        op.f("fk_attendance_recurring_block_id_recurring_blocks"),
        "attendance", "recurring_blocks", ["recurring_block_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(op.f("ck_attendance_hours_positive"), "attendance", "hours > 0")


def downgrade() -> None:
    """Downgrade schema: back to one row per course and day (the first block's row)."""
    op.drop_constraint(op.f("ck_attendance_hours_positive"), "attendance", type_="check")
    op.drop_constraint(op.f("fk_attendance_recurring_block_id_recurring_blocks"), "attendance", type_="foreignkey")
    op.drop_constraint(op.f("uq_attendance_course_date_block"), "attendance", type_="unique")
    op.drop_index(op.f("ix_attendance_recurring_block_id"), table_name="attendance")
    op.execute(
        "DELETE FROM attendance a USING attendance b "
        "WHERE a.course_id = b.course_id AND a.date = b.date AND a.id > b.id"
    )
    op.create_unique_constraint(op.f("uq_attendance_course_date"), "attendance", ["course_id", "date"])
    op.drop_column("attendance", "hours")
    op.drop_column("attendance", "recurring_block_id")
    op.drop_table("attendance_baselines")
