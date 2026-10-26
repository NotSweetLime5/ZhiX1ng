from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, Numeric, Table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.base import col, metadata, now, table

sessions = Table(
    "sessions",
    metadata,
    Column("id", PGUUID(as_uuid=False), primary_key=True),
    col("user_id", BigInteger, fk="users.id"),
    col("agent_id", BigInteger, nullable=True),
    col("title", default="新对话"),
    col("status", default="active"),
    col("pinned", Boolean, False),
    col("message_count", Integer, 0),
    col("token_usage", BigInteger, 0),
    col("last_msg_at", DateTime(timezone=True), nullable=True),
    col("metadata", JSONB, dict),
    col("created_at", DateTime(timezone=True), now),
    col("updated_at", DateTime(timezone=True), now),
)

messages = table(
    "messages",
    col("session_id", PGUUID(as_uuid=False), fk="sessions.id"),
    col("role"),
    col("content"),
    col("reasoning_content", default=""),
    col("tool_calls", JSONB, list),
    col("refs", JSONB, list),
    col("model_name", default=""),
    col("prompt_tokens", Integer, 0),
    col("completion_tokens", Integer, 0),
    col("first_token_ms", Integer, 0),
    col("latency_ms", Integer, 0),
    col("status", Integer, 1),
    col("trace_id", default=""),
    col("metadata", JSONB, dict),
    timestamps=False,
)

usage = table(
    "usage_logs",
    col("user_id", BigInteger),
    col("agent_id", BigInteger, 0),
    col("session_id", PGUUID(as_uuid=False), nullable=True),
    col("message_id", BigInteger, 0),
    col("scene", default="chat"),
    col("model"),
    col("prompt_tokens", Integer, 0),
    col("completion_tokens", Integer, 0),
    col("cost_amount", Numeric(12, 6), 0),
    timestamps=False,
)
