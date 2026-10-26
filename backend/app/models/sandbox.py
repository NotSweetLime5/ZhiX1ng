from sqlalchemy import BigInteger, Integer
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import col, table

sandbox_executions = table(
    "sandbox_executions",
    col("user_id", BigInteger, 0),
    col("tool_call_id"),
    col("language"),
    col("code_hash"),
    col("exit_code", Integer, -1),
    col("duration_ms", Integer, 0),
    col("stdout_head", default=""),
    col("stderr_head", default=""),
    col("metadata", JSONB, dict),
    timestamps=False,
)
