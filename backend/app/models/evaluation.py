from sqlalchemy import BigInteger, Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import col, table

eval_datasets = table(
    "eval_datasets",
    col("name"),
    col("description", default=""),
    col("user_id", BigInteger, fk="users.id"),
    col("scene", default="agent"),
    col("case_count", Integer, 0),
)

eval_cases = table(
    "eval_cases",
    col("dataset_id", BigInteger, fk="eval_datasets.id"),
    col("question"),
    col("expected_answer", default=""),
    col("expected_tools", JSONB, list),
    col("expected_chunk_ids", JSONB, list),
    timestamps=False,
)

eval_runs = table(
    "eval_runs",
    col("dataset_id", BigInteger, fk="eval_datasets.id"),
    col("user_id", BigInteger, fk="users.id"),
    col("agent_id", BigInteger, nullable=True),
    col("config", JSONB, dict),
    col("status", default="pending"),
    col("total", Integer, 0),
    col("passed", Integer, 0),
    col("metrics", JSONB, dict),
    timestamps=False,
)

eval_results = table(
    "eval_results",
    col("run_id", BigInteger, fk="eval_runs.id"),
    col("case_id", BigInteger, fk="eval_cases.id"),
    col("actual_answer", default=""),
    col("tool_trace", JSONB, list),
    col("scores", JSONB, dict),
    col("passed", Boolean, False),
    col("latency_ms", Integer, 0),
    col("tokens", Integer, 0),
    col("error", default=""),
    timestamps=False,
)
