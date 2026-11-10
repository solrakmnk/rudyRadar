"""durable Strava webhook event log, auth status and initial import tracking

Additive only: new nullable/defaulted columns and a new table. No data is
removed. Existing athletes with a completed history are marked as such.
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_webhook_events"
down_revision = "0012_indoor_cardio"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("athletes", sa.Column("auth_status", sa.String(length=30), nullable=False, server_default="connected"))
    op.add_column("athletes", sa.Column("auth_error", sa.String(length=60), nullable=True))
    op.add_column("athletes", sa.Column("auth_error_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("athletes", sa.Column("initial_import_status", sa.String(length=20), nullable=False, server_default="pending"))
    op.add_column("athletes", sa.Column("initial_import_count", sa.Integer(), nullable=True))
    op.add_column("athletes", sa.Column("initial_import_error", sa.String(length=120), nullable=True))
    op.execute("UPDATE athletes SET initial_import_status = 'completed' WHERE history_synced_at IS NOT NULL")

    op.create_table(
        "strava_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.BigInteger(), nullable=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("object_type", sa.String(length=20), nullable=False),
        sa.Column("object_id", sa.BigInteger(), nullable=False),
        sa.Column("aspect_type", sa.String(length=20), nullable=False),
        sa.Column("event_time", sa.BigInteger(), nullable=False),
        sa.Column("updates", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner_id", "object_type", "object_id", "aspect_type", "event_time", name="uq_strava_webhook_event"),
    )
    op.create_index("ix_strava_webhook_events_owner_id", "strava_webhook_events", ["owner_id"])
    op.create_index("ix_strava_webhook_events_status", "strava_webhook_events", ["status"])
    op.create_index("ix_strava_webhook_events_object", "strava_webhook_events", ["object_type", "object_id"])
    op.create_index("ix_strava_webhook_events_due", "strava_webhook_events", ["status", "next_attempt_at"])


def downgrade():
    op.drop_table("strava_webhook_events")
    for column in ("initial_import_error", "initial_import_count", "initial_import_status", "auth_error_at", "auth_error", "auth_status"):
        op.drop_column("athletes", column)
