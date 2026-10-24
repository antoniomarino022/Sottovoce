from functools import lru_cache
import os
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or .env file.

    Sensitive fields use `SecretStr` to prevent accidental exposure
    in logs, tracebacks, or API responses. To retrieve the raw string value:
    `settings.DEEPSEEK_API_KEY.get_secret_value()`
    """

    DEEPSEEK_API_KEY: SecretStr = Field(
        default=SecretStr(""),
        description="DeepSeek API key used for safety triage and roast generation",
    )
    HMAC_SECRET_KEY: SecretStr = Field(
        default=SecretStr(""),
        description="Secret key for pseudonymous user_key derivation via HMAC-SHA256",
    )
    TELEGRAM_BOT_TOKEN: SecretStr = Field(
        default=SecretStr(""),
        description="Telegram bot token issued by BotFather",
    )

    REDIS_URL: SecretStr = Field(
        default=SecretStr("redis://127.0.0.1:6379/0"),
        description="Redis / Upstash connection URL (SecretStr to protect inline credentials)",
    )
    DATABASE_URL: SecretStr = Field(
        default=SecretStr(""),
        description="Neon PostgreSQL pooled connection string",
    )


    TELEGRAM_BOT_USERNAME: str = Field(
        default="HotMicBot",
        description="Telegram bot username (without @) for Mini App deep links",
    )
    TELEGRAM_WEBHOOK_URL: str = Field(
        default="",
        description="Public URL endpoint for Telegram webhook on Vercel",
    )
    WEBAPP_URL: str = Field(
        default="https://hot-mic.vercel.app",
        description="Public URL for Telegram Mini App",
    )
    ADSGRAM_BLOCK_ID: str = Field(
        default="",
        description="Adsgram Block ID for rewarded ads (e.g. 1234 or your Adsgram placement ID)",
    )

    @property
    def is_serverless(self) -> bool:
        """True when running inside Vercel or AWS Lambda serverless functions."""
        return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Returns a cached singleton instance of Settings."""
    return Settings()


# Global instance accessible throughout the project
settings = get_settings()

