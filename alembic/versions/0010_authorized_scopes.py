"""store granted Strava authorization scopes"""

from alembic import op
import sqlalchemy as sa

revision = "0010_authorized_scopes"
down_revision = "0009_activity_categories"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("athletes", sa.Column("authorized_scopes", sa.String(length=200), nullable=True))


def downgrade():
    op.drop_column("athletes", "authorized_scopes")
