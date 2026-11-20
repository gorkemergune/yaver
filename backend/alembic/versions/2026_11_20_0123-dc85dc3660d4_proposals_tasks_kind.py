"""proposals: tasks kind

Revision ID: dc85dc3660d4
Revises: 18e4d9ce57da
Create Date: 2026-11-20 01:23:20.420923+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc85dc3660d4'
down_revision: Union[str, Sequence[str], None] = '18e4d9ce57da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: proposals.kind gains 'tasks' (the weekly plan draft)."""
    op.drop_constraint(op.f("ck_proposals_proposal_kind"), "proposals", type_="check")
    op.create_check_constraint(
        op.f("ck_proposals_proposal_kind"),
        "proposals",
        "kind IN ('schedule', 'events', 'tasks')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM proposals WHERE kind = 'tasks'")
    op.drop_constraint(op.f("ck_proposals_proposal_kind"), "proposals", type_="check")
    op.create_check_constraint(
        op.f("ck_proposals_proposal_kind"), "proposals", "kind IN ('schedule', 'events')"
    )
