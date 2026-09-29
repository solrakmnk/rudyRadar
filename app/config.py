from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://radar_rudy:radar_rudy@db:5432/radar_rudy"
    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_club_id: int = 1187973
    strava_redirect_uri: str = "http://localhost:8000/auth/strava/callback"
    app_base_url: str = "http://localhost:8000"
    app_timezone: str = "America/Mexico_City"
    admin_secret: str = "development-only"
    token_encryption_key: str = ""
    session_secret: str = "development-only"
    strava_sync_enabled: bool = False
    include_virtual_activities: bool = False
    webhook_verify_token: str = ""
    strava_initial_history_days: int = 3650
    strava_rolling_sync_days: int = 21

@lru_cache
def get_settings() -> Settings:
    return Settings()
