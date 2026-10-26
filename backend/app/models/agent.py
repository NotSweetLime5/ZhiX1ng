from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import col, table

agents = table(
    "agents",
    col("name"),
    col("description", default=""),
    col("type", default="expert"),
    col("creator_id", BigInteger, fk="users.id"),
    col("system_prompt", default=""),
    col("model_config_id", BigInteger, fk="model_configs.id"),
    col("fallback_model_config_id", BigInteger, nullable=True),
    col("temperature", Numeric, 0.7),
    col("top_p", Numeric, 0.9),
    col("max_tokens", Integer, 4096),
    col("max_iterations", Integer, 10),
    col("memory_enabled", Boolean, True),
    col("memory_window", Integer, 20),
    col("memory_long_enabled", Boolean, False),
    col("kb_ids", JSONB, list),
    col("tools", JSONB, list),
    col("is_preset", Boolean, False),
    col("config", JSONB, dict),
    col("status", Integer, 1),
)

mcp_servers = table(
    "mcp_servers",
    col("name"),
    col("transport", default="streamable_http"),
    col("url", default=""),
    col("command", default=""),
    col("args", JSONB, list),
    col("env", JSONB, dict),
    col("headers", JSONB, dict),
    col("status", default="disconnected"),
    col("last_health_at", DateTime(timezone=True), nullable=True),
    col("tools_cache", JSONB, list),
)

tools = table(
    "tools",
    col("code", String(64)),
    col("name"),
    col("type", default="builtin"),
    col("description"),
    col("parameters", JSONB, dict),
    col("handler", default=""),
    col("mcp_server_id", BigInteger, nullable=True, fk="mcp_servers.id"),
    col("endpoint", default=""),
    col("auth_config", JSONB, dict),
    col("default_config", JSONB, dict),
    col("timeout_ms", Integer, 30000),
    col("is_dangerous", Boolean, False),
    col("status", Integer, 1),
    constraints=(UniqueConstraint("code"),),
)

a2a_agents = table(
    "a2a_agents",
    col("name"),
    col("base_url"),
    col("card", JSONB, dict),
    col("status", default="unknown"),
    col("last_health_at", DateTime(timezone=True), nullable=True),
)
