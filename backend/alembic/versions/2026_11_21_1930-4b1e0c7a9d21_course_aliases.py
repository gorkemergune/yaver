"""course aliases

Revision ID: 4b1e0c7a9d21
Revises: d37bc5b1bb0c
Create Date: 2026-11-21 19:30:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4b1e0c7a9d21'
down_revision: Union[str, Sequence[str], None] = 'd37bc5b1bb0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # other names the user calls a course by ("DSA", "Veri Yapıları", "Data Structures")
    op.add_column(
        'courses',
        sa.Column(
            'aliases',
            postgresql.ARRAY(sa.String(length=60)),
            server_default='{}',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('courses', 'aliases')
