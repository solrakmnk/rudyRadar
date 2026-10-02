"""classify existing indoor cardio activities"""

from alembic import op

revision = "0012_indoor_cardio"
down_revision = "0011_activity_visibility"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE activities SET normalized_sport = 'cardio' "
        "WHERE sport_type IN ('Elliptical', 'StairStepper', 'Rowing', 'IndoorRowing')"
    )


def downgrade():
    op.execute(
        "UPDATE activities SET normalized_sport = NULL "
        "WHERE normalized_sport = 'cardio' AND sport_type IN ('Elliptical', 'StairStepper', 'Rowing', 'IndoorRowing')"
    )
