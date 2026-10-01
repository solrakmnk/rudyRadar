"""track club membership verification attempts"""

from alembic import op
import sqlalchemy as sa

revision = "0008_membership_verification"
down_revision = "0007_walk_hike"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("athletes", sa.Column("membership_check_status", sa.String(length=30), nullable=False, server_default="pending"))
    op.add_column("athletes", sa.Column("membership_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("athletes", sa.Column("membership_check_error", sa.String(length=120), nullable=True))
    op.execute("UPDATE athletes SET membership_check_status = CASE WHEN is_club_member THEN 'verified' ELSE 'not_member' END, membership_checked_at = connected_at")


def downgrade():
    op.drop_column("athletes", "membership_check_error")
    op.drop_column("athletes", "membership_checked_at")
    op.drop_column("athletes", "membership_check_status")
