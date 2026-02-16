"""Configuration management using Pydantic settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel
from typing import Optional


class MemoryConfig(BaseModel):
    """Configuration for the five-tier memory system."""

    # Use legacy adapters (SemanticMemory, EpisodicMemory, ProceduralMemory)
    # instead of new ChromaDB/SQLite backends
    use_legacy: bool = False

    # Root directory for all memory persistence
    data_dir: str = "data/memory"

    # ChromaDB embedding model: "default" uses ONNX, "sentence-transformers"
    # requires the sentence-transformers package.
    embedding_model: str = "default"

    # Working memory defaults
    wm_decay_rate: float = 0.95
    wm_default_max_tokens: int = 4000


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM API Keys
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # Mock Mode
    mock_mode: bool = True

    # Logging
    log_level: str = "INFO"

    # Legacy memory paths (kept for backward compatibility)
    episodic_db_path: str = "data/memory/episodic.db"
    procedural_json_path: str = "data/memory/workflows.json"

    # Database path for collected data
    startup_db_path: str = "data/collected/startups.db"

    # Customer simulation seed data
    customer_seed_path: str = "data/seed/customers.json"
    customer_hypotheses_path: str = "data/seed/customer_hypotheses.json"
    # New memory system settings (flat, loaded from env)
    memory_use_legacy: bool = False
    memory_data_dir: str = "data/memory"
    memory_embedding_model: str = "default"
    memory_wm_decay_rate: float = 0.95
    memory_wm_default_max_tokens: int = 4000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    def get_memory_config(self) -> MemoryConfig:
        """Build a MemoryConfig from the flat settings."""
        return MemoryConfig(
            use_legacy=self.memory_use_legacy,
            data_dir=self.memory_data_dir,
            embedding_model=self.memory_embedding_model,
            wm_decay_rate=self.memory_wm_decay_rate,
            wm_default_max_tokens=self.memory_wm_default_max_tokens,
        )


# Global settings instance
settings = Settings()
