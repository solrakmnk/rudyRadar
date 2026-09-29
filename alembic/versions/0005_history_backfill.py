"""record completion of the initial activity-summary backfill"""

from alembic import op
import sqlalchemy as sa

revision = "0005_history_backfill"
down_revision = "0004_open_water"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("athletes", sa.Column("history_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("athletes", "history_synced_at")
