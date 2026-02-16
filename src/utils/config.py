"""Configuration management using Pydantic settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM API Keys
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # Mock Mode
    mock_mode: bool = True

    # Logging
    log_level: str = "INFO"

    # Memory paths
    episodic_db_path: str = "data/memory/episodic.db"
    procedural_json_path: str = "data/memory/workflows.json"

    # Database path for collected data
    startup_db_path: str = "data/collected/startups.db"

    # Customer simulation seed data
    customer_seed_path: str = "data/seed/customers.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


# Global settings instance
settings = Settings()
