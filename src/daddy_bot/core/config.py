from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_start_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_START_MODEL")

    rapidapi_key: str | None = Field(default=None, alias="RAPIDAPI_KEY")
    google_maps_api_key: str | None = Field(default=None, alias="GOOGLE_MAPS_API_KEY")

    rate_limit_max_events: int = Field(default=8, alias="RATE_LIMIT_MAX_EVENTS")
    rate_limit_window_seconds: int = Field(default=10, alias="RATE_LIMIT_WINDOW_SECONDS")
    rate_limit_cooldown_message: str = Field(
        default="Doucement champion, respire 2 secondes et recommence.",
        alias="RATE_LIMIT_COOLDOWN_MESSAGE",
    )
    owner_ids: str | None = Field(default=None, alias="OWNER_IDS")
    bibine_channel_id: int | None = Field(default=None, alias="BIBINE_CHANNEL_ID")
    bibine_timezone: str = Field(default="Europe/Paris", alias="BIBINE_TIMEZONE")

    princesse_morning_enabled: bool = Field(default=True, alias="PRINCESSE_MORNING_ENABLED")
    princesse_morning_timezone: str = Field(default="Europe/Paris", alias="PRINCESSE_MORNING_TIMEZONE")
    princesse_morning_start_hour: int = Field(default=6, ge=0, le=23, alias="PRINCESSE_MORNING_START_HOUR")
    princesse_morning_end_hour: int = Field(default=10, ge=1, le=23, alias="PRINCESSE_MORNING_END_HOUR")

    @model_validator(mode="after")
    def _princesse_morning_window(self) -> "Settings":
        if self.princesse_morning_end_hour <= self.princesse_morning_start_hour:
            raise ValueError(
                "PRINCESSE_MORNING_END_HOUR must be greater than PRINCESSE_MORNING_START_HOUR "
                "(morning window is [start, end) in local time, e.g. 6 and 10 for 06:00–10:00)."
            )
        return self

    def owner_id_set(self) -> set[int]:
        if not self.owner_ids:
            return set()
        parsed: set[int] = set()
        for value in self.owner_ids.split(","):
            value = value.strip()
            if value:
                parsed.add(int(value))
        return parsed


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
