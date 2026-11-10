from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Athlete(Base):
    __tablename__ = "athletes"
    id: Mapped[int] = mapped_column(primary_key=True)
    strava_athlete_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    firstname: Mapped[str] = mapped_column(String(100))
    lastname: Mapped[str] = mapped_column(String(100), default="")
    profile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(String, default="")
    refresh_token_encrypted: Mapped[str] = mapped_column(String, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorized_scopes: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_club_member: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    membership_check_status: Mapped[str] = mapped_column(String(30), default="pending")
    membership_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    membership_check_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    history_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # connected | reauth_required. reauth_required athletes are skipped by every Strava call.
    auth_status: Mapped[str] = mapped_column(String(30), default="connected", server_default="connected")
    auth_error: Mapped[str | None] = mapped_column(String(60), nullable=True)
    auth_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # pending | running | completed | failed — result of the one-time history import.
    initial_import_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    initial_import_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    initial_import_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    activities: Mapped[list["Activity"]] = relationship(back_populates="athlete", cascade="all, delete-orphan")

class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("strava_activity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), index=True)
    strava_activity_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(255))
    sport_type: Mapped[str] = mapped_column(String(50))
    normalized_sport: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    start_date_local: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    distance_m: Mapped[float] = mapped_column(Float, default=0)
    moving_time_s: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_time_s: Mapped[int] = mapped_column(Integer, default=0)
    total_elevation_gain_m: Mapped[float] = mapped_column(Float, default=0)
    average_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    suffer_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    workout_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    trainer: Mapped[bool] = mapped_column(Boolean, default=False)
    commute: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    athlete: Mapped[Athlete] = relationship(back_populates="activities")


class StravaWebhookEvent(Base):
    """Durable log of every webhook delivery, used for idempotency, retries and diagnosis.

    Only identifiers and Strava's ``updates`` map are stored: no tokens and no
    activity content.
    """
    __tablename__ = "strava_webhook_events"
    __table_args__ = (
        UniqueConstraint("owner_id", "object_type", "object_id", "aspect_type", "event_time", name="uq_strava_webhook_event"),
        Index("ix_strava_webhook_events_object", "object_type", "object_id"),
        Index("ix_strava_webhook_events_due", "status", "next_attempt_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    object_type: Mapped[str] = mapped_column(String(20))
    object_id: Mapped[int] = mapped_column(BigInteger)
    aspect_type: Mapped[str] = mapped_column(String(20))
    event_time: Mapped[int] = mapped_column(BigInteger)
    updates: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending | processing | retry | processed | ignored | failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
