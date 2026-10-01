"""clarify strength and mobility activity categories"""

from alembic import op

revision = "0009_activity_categories"
down_revision = "0008_membership_verification"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE activities SET normalized_sport = 'strength' WHERE sport_type IN ('WeightTraining', 'Crossfit', 'HighIntensityIntervalTraining', 'Workout')")
    op.execute("UPDATE activities SET normalized_sport = 'wellbeing' WHERE sport_type IN ('Yoga', 'Pilates', 'PhysicalTherapy')")


def downgrade():
    op.execute("UPDATE activities SET normalized_sport = 'wellbeing' WHERE sport_type = 'Workout'")
