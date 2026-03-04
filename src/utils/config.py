"""Configuration management using Pydantic settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM API Keys
    openrouter_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # External service keys
    serper_api_key: Optional[str] = None

    # LLM model identifiers (litellm format)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = ""
    coordinator_model: Optional[str] = None
    product_model: Optional[str] = None
    developer_model: Optional[str] = None
    reviewer_model: Optional[str] = None
    customer_model: Optional[str] = None
    anthropic_model: str = "anthropic/claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o-mini"

    # Mock Mode
    mock_mode: bool = True

    # Logging
    log_level: str = "INFO"

    # CrewAI runtime paths (kept local for constrained/sandbox execution)
    crewai_local_appdata_dir: str = "data/crewai_local"
    crewai_db_storage_dir: str = "data/crewai_storage"
    crewai_storage_namespace: str = "autonomous-startup"

    # Database path for collected data
    startup_db_path: str = "data/collected/startups.db"

    # Memory system settings
    memory_data_dir: str = "data/memory"
    generated_tools_dir: str = "data/generated_tools"
    generated_tools_retention_days: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


# Global settings instance
settings = Settings()
