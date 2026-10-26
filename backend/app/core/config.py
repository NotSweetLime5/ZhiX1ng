from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NX_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://nexus:nexus123@127.0.0.1:5439/nexus_agent"
    redis_url: str = "redis://127.0.0.1:6383/0"
    milvus_uri: str = "http://127.0.0.1:19533"
    minio_endpoint: str = "127.0.0.1:9003"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "nexus-docs"
    minio_secure: bool = False
    jwt_secret: str = "nexus-local-jwt-change-before-deployment"
    secret_key: str = "nexus-local-encryption-change-before-deployment"
    admin_password: str = "admin123"
    access_ttl: int = 900
    refresh_ttl: int = 604800
    default_chat: str = "deepseek-chat"
    default_embedding: str = "bge-m3"
    searxng_url: str = "http://127.0.0.1:8083/search"
    allowed_http_hosts: list[str] = []
    sandbox_enabled: bool = False
    sandbox_image: str = "nexus-python-sandbox:local"
    file_root: str = "./data/files"
    step_timeout: int = 60
    run_timeout: int = 300
    memory_extract_every: int = 6
    otel_endpoint: str = ""
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def checkpoint_url(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def settings() -> Settings:
    return Settings()
