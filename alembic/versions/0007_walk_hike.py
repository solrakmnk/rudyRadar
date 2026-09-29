"""include walking and hiking in the radar"""

from alembic import op

revision = "0007_walk_hike"
down_revision = "0006_strength_wellbeing"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE activities SET normalized_sport = 'walk' WHERE sport_type IN ('Walk', 'Hike')")


def downgrade():
    op.execute("UPDATE activities SET normalized_sport = NULL WHERE normalized_sport = 'walk'")
