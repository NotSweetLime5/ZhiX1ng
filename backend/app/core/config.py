from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZHIXING_", env_file=".env", extra="ignore")
    env: str = "dev"
    database_url: str = "postgresql+asyncpg://nexus:nexus123@127.0.0.1:5439/zhixing_python"
    redis_url: str = "redis://127.0.0.1:6383/0"
    redis_namespace: str = Field("nx", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    milvus_uri: str = "http://127.0.0.1:19533"
    milvus_database: str = Field("zhixing_python", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    milvus_namespace: str = Field("", pattern=r"^(?:[A-Za-z][A-Za-z0-9_]{0,63})?$")
    minio_endpoint: str = "127.0.0.1:9003"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "zhixing-python-docs"
    minio_secure: bool = False
    jwt_secret: str = "nexus-local-jwt-change-before-deployment"
    secret_key: str = "nexus-local-encryption-change-before-deployment"
    admin_password: str = ""
    access_ttl: int = 900
    refresh_ttl: int = 604800
    default_chat: str = "deepseek-chat"
    default_embedding: str = "bge-m3"
    searxng_url: str = "http://127.0.0.1:8083/search"
    allowed_http_hosts: list[str] = []
    sandbox_enabled: bool = False
    sandbox_image: str = "zhixing-sandbox:local"
    file_root: str = "./data/files"
    step_timeout: int = 60
    run_timeout: int = 300
    llm_max_conns: int = Field(16, ge=1)
    llm_circuit_window: int = Field(20, ge=1)
    llm_circuit_error_rate: float = Field(0.3, gt=0, le=1)
    llm_circuit_open: float = Field(60, gt=0)
    llm_retries: int = Field(2, ge=0, le=10)
    rag_dense_top_k: int = Field(25, ge=1, le=1000)
    rag_sparse_top_k: int = Field(25, ge=1, le=1000)
    rag_fused_top_n: int = Field(15, ge=1, le=1000)
    rag_final_top_k: int = Field(5, ge=1, le=1000)
    rag_rrf_k: int = Field(60, ge=1)
    rag_score_threshold: float = Field(0.35, ge=0, le=1)
    rag_batch_embed: int = Field(64, ge=1, le=1024)
    worker_concurrency: int = Field(4, ge=1, le=64)
    worker_max_retry: int = Field(3, ge=1, le=20)
    worker_claim_idle_ms: int = Field(90000, ge=90000)
    a2a_port: int = Field(8082, ge=1, le=65535)
    a2a_allow_anonymous: bool = True
    mcp_port: int = Field(8086, ge=1, le=65535)
    sandbox_timeout: int = Field(30, ge=1, le=300)
    memory_extract_every: int = 6
    otel_endpoint: str = ""
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @model_validator(mode="after")
    def production_secrets(self):
        if self.env.lower() in {"prod", "production"}:
            defaults = {
                "nexus-local-jwt-change-before-deployment",
                "nexus-local-encryption-change-before-deployment",
                "replace-with-a-random-secret",
                "replace-with-an-independent-random-secret",
                "change-me-in-prod",
                "change-me-32-bytes!!",
            }
            if any(len(secret) < 32 or secret in defaults for secret in (self.jwt_secret, self.secret_key)):
                raise ValueError("生产环境的 ZHIXING_JWT_SECRET 和 ZHIXING_SECRET_KEY 必须为至少32字符的独立密钥")
            if self.jwt_secret == self.secret_key:
                raise ValueError("ZHIXING_JWT_SECRET 和 ZHIXING_SECRET_KEY 不能相同")
        return self

    @property
    def checkpoint_url(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def settings() -> Settings:
    return Settings()
