"""store Strava activity visibility"""

from alembic import op
import sqlalchemy as sa

revision = "0011_activity_visibility"
down_revision = "0010_authorized_scopes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activities", sa.Column("visibility", sa.String(length=30), nullable=True))
    op.create_index("ix_activities_visibility", "activities", ["visibility"])


def downgrade():
    op.drop_index("ix_activities_visibility", table_name="activities")
    op.drop_column("activities", "visibility")
