from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8443
    database_url: str = "sqlite:///./social_networks.db"

    jwt_secret: str = Field(min_length=32)
    jwt_expires_minutes: int = Field(default=60, ge=1)
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)

    cors_origins: str = ""

    rate_limit_enabled: bool = True
    rate_limit_per_hour: int = Field(default=1000, ge=1)
    login_rate_limit: int = Field(default=5, ge=1)
    login_rate_window_minutes: int = Field(default=15, ge=1)
    max_body_bytes: int = Field(default=10 * 1024, ge=1024)

    ssl_key_path: str | None = None
    ssl_cert_path: str | None = None

    docs_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        if any(err["loc"] == ("jwt_secret",) for err in exc.errors()):
            raise RuntimeError(
                "JWT_SECRET manquant ou trop court dans .env (32 caractères minimum)"
            ) from exc
        raise
