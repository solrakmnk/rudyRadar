"""support current Strava identifiers"""
from alembic import op
import sqlalchemy as sa

revision = "0002_strava_ids_bigint"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column("athletes", "strava_athlete_id", type_=sa.BigInteger(), existing_type=sa.Integer())
    op.alter_column("activities", "strava_activity_id", type_=sa.BigInteger(), existing_type=sa.Integer())

def downgrade():
    op.alter_column("activities", "strava_activity_id", type_=sa.Integer(), existing_type=sa.BigInteger())
    op.alter_column("athletes", "strava_athlete_id", type_=sa.Integer(), existing_type=sa.BigInteger())
