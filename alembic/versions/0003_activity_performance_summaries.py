"""store permitted activity performance summaries"""
from alembic import op
import sqlalchemy as sa

revision = "0003_perf_summaries"
down_revision = "0002_strava_ids_bigint"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("activities", sa.Column("average_speed_mps", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("max_speed_mps", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("calories", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("suffer_score", sa.Float(), nullable=True))
    op.add_column("activities", sa.Column("workout_type", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("activities", "workout_type")
    op.drop_column("activities", "suffer_score")
    op.drop_column("activities", "calories")
    op.drop_column("activities", "max_speed_mps")
    op.drop_column("activities", "average_speed_mps")
