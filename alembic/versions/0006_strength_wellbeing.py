"""separate strength and wellbeing from generic workouts"""

from alembic import op

revision = "0006_strength_wellbeing"
down_revision = "0005_history_backfill"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE activities SET normalized_sport = 'strength' WHERE sport_type IN ('WeightTraining', 'Crossfit', 'HighIntensityIntervalTraining')")
    op.execute("UPDATE activities SET normalized_sport = 'wellbeing' WHERE sport_type IN ('Yoga', 'Pilates', 'Workout', 'PhysicalTherapy')")


def downgrade():
    op.execute("UPDATE activities SET normalized_sport = 'gym' WHERE normalized_sport IN ('strength', 'wellbeing')")
