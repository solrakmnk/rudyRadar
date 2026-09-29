"""separate historical open-water swimming summaries"""

from alembic import op


revision = "0004_open_water"
down_revision = "0003_perf_summaries"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE activities SET normalized_sport = 'open_water' WHERE sport_type = 'Swim' AND workout_type = 2")


def downgrade():
    op.execute("UPDATE activities SET normalized_sport = 'swim' WHERE normalized_sport = 'open_water'")
