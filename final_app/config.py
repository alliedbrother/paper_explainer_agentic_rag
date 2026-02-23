"""Configuration settings for the RAG application."""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import model_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "Agentic RAG System"
    debug: bool = False

    # PostgreSQL - REQUIRED secrets (no defaults for security)
    postgres_host: str = "localhost"
    postgres_port: int = 5432  # Standard PostgreSQL/RDS port
    postgres_user: str  # REQUIRED - no default
    postgres_password: str  # REQUIRED - no default
    postgres_db: str = "ragdb"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str | None = None
    qdrant_url: str | None = None
    qdrant_collection: str = "research_papers"
    qdrant_timeout: int = 10  # Timeout in seconds for Qdrant operations

    # OpenAI - REQUIRED
    openai_api_key: str  # REQUIRED - no default
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout: float = 30.0  # Timeout in seconds for OpenAI API calls
    openai_max_retries: int = 2  # Max retries for OpenAI API calls

    # Agent execution
    agent_timeout: float = 120.0  # Timeout in seconds for agent execution

    # Cohere (for reranking)
    cohere_api_key: str | None = None

    # LangSmith (optional)
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "agentic-rag"
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None

    # OpenWeatherMap
    openweathermap_api_key: str | None = None

    # S3 (for paper webpages)
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_bucket: str = "paper-blogs"
    s3_region: str = "us-east-1"

    # PDF Storage
    pdf_storage_dir: str = "./data/pdfs"

    # Redis (for rate limiting)
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    # Rate Limiting - Per User (Free tier)
    rate_limit_requests_per_minute_free: int = 3  # Free users: 3 req/min
    rate_limit_tokens_per_minute_free: int = 100  # Free users: 100 tokens/min

    # Rate Limiting - Per User (Power tier)
    rate_limit_requests_per_minute_power: int = 30  # Power users: 30 req/min
    rate_limit_tokens_per_minute_power: int = 20000  # Power users: 20,000 tokens/min

    # Rate Limiting - Per User (Super tier) - Unlimited (no limits enforced)

    # Rate Limiting - Global System
    global_rate_limit_requests_per_minute: int = 400  # System-wide limit: 400 req/min
    global_queue_max_size: int = 100  # Max requests in queue
    global_queue_max_wait_seconds: int = 60  # Max wait time before timeout

    # Response Caching (Semantic)
    cache_ttl_seconds: int = 3600  # Default cache TTL: 1 hour
    cache_similarity_threshold: float = 0.75  # Cosine similarity threshold for semantic cache (0.75 = similar questions)
    cache_max_items_per_tenant: int = 25  # Max cached items per tenant (LRU eviction)

    @property
    def redis_url(self) -> str:
        """Construct Redis connection URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def postgres_url(self) -> str:
        """Construct PostgreSQL connection URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_async_url(self) -> str:
        """Construct async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # File upload limits
    max_file_size_mb: int = 50  # Maximum file size in MB

    @model_validator(mode='after')
    def validate_required_secrets(self):
        """Validate that required secrets are provided and not empty."""
        if not self.postgres_user:
            raise ValueError("POSTGRES_USER is required - set it in .env file")
        if not self.postgres_password:
            raise ValueError("POSTGRES_PASSWORD is required - set it in .env file")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required - set it in .env file")
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra fields in .env


# Also try loading from the package directory
import os
_package_dir = os.path.dirname(os.path.abspath(__file__))
_env_file = os.path.join(_package_dir, ".env")
if os.path.exists(_env_file):
    from dotenv import load_dotenv
    load_dotenv(_env_file, override=True)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
