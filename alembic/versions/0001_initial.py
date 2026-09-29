"""initial schema"""
from alembic import op
import sqlalchemy as sa
revision="0001_initial"
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("athletes",sa.Column("id",sa.Integer,primary_key=True),sa.Column("strava_athlete_id",sa.Integer,nullable=False,unique=True),sa.Column("firstname",sa.String(100),nullable=False),sa.Column("lastname",sa.String(100),nullable=False),sa.Column("profile_url",sa.String(500)),sa.Column("access_token_encrypted",sa.String,nullable=False),sa.Column("refresh_token_encrypted",sa.String,nullable=False),sa.Column("token_expires_at",sa.DateTime(timezone=True)),sa.Column("is_club_member",sa.Boolean,nullable=False),sa.Column("is_active",sa.Boolean,nullable=False),sa.Column("connected_at",sa.DateTime(timezone=True),server_default=sa.func.now()),sa.Column("last_sync_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now()))
    op.create_index("ix_athletes_strava_athlete_id","athletes",["strava_athlete_id"])
    op.create_table("activities",sa.Column("id",sa.Integer,primary_key=True),sa.Column("athlete_id",sa.Integer,sa.ForeignKey("athletes.id"),nullable=False),sa.Column("strava_activity_id",sa.Integer,nullable=False,unique=True),sa.Column("name",sa.String(255),nullable=False),sa.Column("sport_type",sa.String(50),nullable=False),sa.Column("normalized_sport",sa.String(10)),sa.Column("start_date",sa.DateTime(timezone=True),nullable=False),sa.Column("start_date_local",sa.DateTime(timezone=True)),sa.Column("timezone",sa.String(80)),sa.Column("distance_m",sa.Float,nullable=False),sa.Column("moving_time_s",sa.Integer,nullable=False),sa.Column("elapsed_time_s",sa.Integer,nullable=False),sa.Column("total_elevation_gain_m",sa.Float,nullable=False),sa.Column("manual",sa.Boolean,nullable=False),sa.Column("trainer",sa.Boolean,nullable=False),sa.Column("commute",sa.Boolean,nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now()))
    op.create_index("ix_activities_athlete_id","activities",["athlete_id"]);op.create_index("ix_activities_strava_activity_id","activities",["strava_activity_id"]);op.create_index("ix_activities_start_date","activities",["start_date"]);op.create_index("ix_activities_normalized_sport","activities",["normalized_sport"])
def downgrade():
    op.drop_table("activities");op.drop_table("athletes")
