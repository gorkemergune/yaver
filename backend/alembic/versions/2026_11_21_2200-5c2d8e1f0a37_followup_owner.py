"""followup owner

Revision ID: 5c2d8e1f0a37
Revises: 4b1e0c7a9d21
Create Date: 2026-11-21 22:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c2d8e1f0a37'
down_revision: Union[str, Sequence[str], None] = '4b1e0c7a9d21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # whose follow-up it is (agents.yaml id); NULL = the agenda employee's
    op.add_column('followups', sa.Column('owner_id', sa.String(length=40), nullable=True))
    # existing rows: the startup repo's dated items are Venture's, applications Mentor's
    op.execute("UPDATE followups SET owner_id = 'startup' WHERE notes LIKE '[github:%'")
    op.execute(
        "UPDATE followups SET owner_id = 'career' WHERE owner_id IS NULL AND ("
        "lower(title) LIKE '%staj%' OR lower(title) LIKE '%başvuru%' "
        "OR lower(title) LIKE '%mülakat%' OR lower(title) LIKE '%intern%' "
        "OR lower(title) LIKE '%iş teklif%')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('followups', 'owner_id')
