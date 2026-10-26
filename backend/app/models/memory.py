from sqlalchemy import BigInteger, DateTime, Integer

from app.models.base import col, table

memories = table(
    "memories",
    col("user_id", BigInteger, fk="users.id"),
    col("agent_id", BigInteger, nullable=True),
    col("content"),
    col("vector_id", default=""),
    col("scope", default="user"),
    col("importance", Integer, 5),
    col("hit_count", Integer, 0),
    col("last_hit_at", DateTime(timezone=True), nullable=True),
    col("status", Integer, 1),
)
