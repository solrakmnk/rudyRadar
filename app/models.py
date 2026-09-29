from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
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
    is_club_member: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    athlete: Mapped[Athlete] = relationship(back_populates="activities")
