"""Application configuration loaded from environment variables."""

from decimal import Decimal
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """
    Central configuration for the Client Portfolio Portal.
    Fails loudly if required variables (DATABASE_URL, JWT_SECRET) are missing.
    """

    # Database (required — no defaults)
    DATABASE_URL: str = Field(
        ...,
        description="Async database URL (postgresql+asyncpg://...)",
    )
    DATABASE_URL_SYNC: str = Field(
        default="",
        description="Sync database URL for scripts (postgresql://...)",
    )

    # Auth (required — no default for secret)
    JWT_SECRET: str = Field(
        ...,
        description="HS256 signing key — generate with: openssl rand -hex 32",
    )
    JWT_EXPIRY_HOURS: int = Field(default=48, ge=1, le=720)

    # Application
    APP_NAME: str = Field(default="JSL Client Portfolio Portal")
    APP_PORT: int = Field(default=8007, ge=1024, le=65535)
    APP_ENV: str = Field(default="development")
    APP_VERSION: str = Field(default="1.0.0")
    CORS_ORIGINS: str = Field(default="http://localhost:3000")

    # Risk computation
    RISK_FREE_RATE: Decimal = Field(
        default=Decimal("6.50"),
        description="India 10Y govt bond yield proxy (%)",
    )

    # Logging
    LOG_LEVEL: str = Field(default="INFO")

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or not v.startswith("postgresql"):
            raise ValueError(
                "DATABASE_URL must be a valid PostgreSQL connection string "
                "starting with 'postgresql+asyncpg://' or 'postgresql://'"
            )
        return v

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if not v or len(v) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters. "
                "Generate with: openssl rand -hex 32"
            )
        return v

    @field_validator("DATABASE_URL_SYNC", mode="before")
    @classmethod
    def derive_sync_url(cls, v: str, info) -> str:
        if v:
            return v
        async_url = info.data.get("DATABASE_URL", "")
        if async_url:
            return async_url.replace("postgresql+asyncpg://", "postgresql://")
        return ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


def get_settings() -> Settings:
    """
    Factory function for Settings.
    Raises ValidationError with clear messages if required vars are missing.
    """
    return Settings()
