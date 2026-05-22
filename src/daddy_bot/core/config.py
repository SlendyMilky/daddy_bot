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
    princesse_morning_chat_ids: str | None = Field(
        default="-1001153426467,-1001805681499",
        alias="PRINCESSE_MORNING_CHAT_IDS",
    )
    princesse_morning_send_chance: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        alias="PRINCESSE_MORNING_SEND_CHANCE",
    )

    # --- Admin web panel ---------------------------------------------------------
    admin_web_enabled: bool = Field(default=True, alias="ADMIN_WEB_ENABLED")
    admin_web_port: int = Field(default=8080, alias="ADMIN_WEB_PORT")
    admin_web_public_url: str = Field(default="http://localhost:8080", alias="ADMIN_WEB_PUBLIC_URL")
    admin_web_secret_key: str | None = Field(default=None, alias="ADMIN_WEB_SECRET_KEY")
    admin_session_ttl_hours: int = Field(default=168, alias="ADMIN_SESSION_TTL_HOURS")

    telegram_oidc_client_id: str | None = Field(default=None, alias="TELEGRAM_OIDC_CLIENT_ID")
    telegram_oidc_client_secret: str | None = Field(default=None, alias="TELEGRAM_OIDC_CLIENT_SECRET")
    telegram_oidc_discovery_url: str = Field(
        default="https://oauth.telegram.org/.well-known/openid-configuration",
        alias="TELEGRAM_OIDC_DISCOVERY_URL",
    )

    @model_validator(mode="after")
    def _princesse_morning_window(self) -> "Settings":
        if self.princesse_morning_end_hour <= self.princesse_morning_start_hour:
            raise ValueError(
                "PRINCESSE_MORNING_END_HOUR must be greater than PRINCESSE_MORNING_START_HOUR "
                "(morning window is [start, end) in local time, e.g. 6 and 10 for 06:00–10:00)."
            )
        return self

    def princesse_morning_chat_id_tuple(self) -> tuple[int, ...]:
        if not self.princesse_morning_chat_ids:
            return ()
        out: list[int] = []
        for value in self.princesse_morning_chat_ids.split(","):
            value = value.strip()
            if not value:
                continue
            try:
                out.append(int(value))
            except ValueError:
                continue
        return tuple(out)

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
