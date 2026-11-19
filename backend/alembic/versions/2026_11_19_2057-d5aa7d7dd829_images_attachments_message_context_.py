"""images: attachments, message context, generic proposals

Revision ID: d5aa7d7dd829
Revises: ac9ae03ea93c
Create Date: 2026-11-19 20:57:57.538215+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd5aa7d7dd829'
down_revision: Union[str, Sequence[str], None] = 'ac9ae03ea93c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # schedule_proposals -> proposals (rows kept), with a kind column.
    op.rename_table("schedule_proposals", "proposals")
    op.execute("ALTER SEQUENCE schedule_proposals_id_seq RENAME TO proposals_id_seq")
    op.execute("ALTER TABLE proposals RENAME CONSTRAINT pk_schedule_proposals TO pk_proposals")
    op.execute(
        "ALTER TABLE proposals RENAME CONSTRAINT fk_schedule_proposals_conversation_id_conversations"
        " TO fk_proposals_conversation_id_conversations"
    )
    op.execute(
        "ALTER TABLE proposals RENAME CONSTRAINT ck_schedule_proposals_proposal_status"
        " TO ck_proposals_proposal_status"
    )
    op.execute(
        "ALTER INDEX ix_schedule_proposals_conversation_id RENAME TO ix_proposals_conversation_id"
    )
    op.add_column(
        "proposals",
        sa.Column(
            "kind",
            sa.Enum(
                "schedule", "events", name="proposal_kind", native_enum=False, create_constraint=True
            ),
            server_default="schedule",
            nullable=False,
        ),
    )

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("mime", sa.String(length=50), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_attachments_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    op.create_index(op.f("ix_attachments_message_id"), "attachments", ["message_id"], unique=False)
    op.add_column("messages", sa.Column("context", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("messages", "context")
    op.drop_index(op.f("ix_attachments_message_id"), table_name="attachments")
    op.drop_table("attachments")

    op.execute("DELETE FROM proposals WHERE kind <> 'schedule'")
    op.drop_constraint(op.f("ck_proposals_proposal_kind"), "proposals", type_="check")
    op.drop_column("proposals", "kind")
    op.execute(
        "ALTER INDEX ix_proposals_conversation_id RENAME TO ix_schedule_proposals_conversation_id"
    )
    op.execute(
        "ALTER TABLE proposals RENAME CONSTRAINT ck_proposals_proposal_status"
        " TO ck_schedule_proposals_proposal_status"
    )
    op.execute(
        "ALTER TABLE proposals RENAME CONSTRAINT fk_proposals_conversation_id_conversations"
        " TO fk_schedule_proposals_conversation_id_conversations"
    )
    op.execute("ALTER TABLE proposals RENAME CONSTRAINT pk_proposals TO pk_schedule_proposals")
    op.execute("ALTER SEQUENCE proposals_id_seq RENAME TO schedule_proposals_id_seq")
    op.rename_table("proposals", "schedule_proposals")
