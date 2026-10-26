from sqlalchemy import BigInteger, Boolean, DateTime, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import col, now, table

workflows = table(
    "workflows",
    col("name"),
    col("description", default=""),
    col("dsl"),
    col("version", Integer, 1),
    col("is_active", Boolean, True),
    col("creator_id", BigInteger, fk="users.id"),
    col("status", Integer, 1),
)

runs = table(
    "workflow_runs",
    col("workflow_id", BigInteger, fk="workflows.id"),
    col("user_id", BigInteger, fk="users.id"),
    col("trigger_type", default="manual"),
    col("status", default="running"),
    col("input", JSONB, dict),
    col("output", JSONB, dict),
    col("dsl_snapshot"),
    col("error", default=""),
    col("trace_id", default=""),
    col("started_at", DateTime(timezone=True), now),
    col("finished_at", DateTime(timezone=True), nullable=True),
    timestamps=False,
)

steps = table(
    "workflow_step_runs",
    col("run_id", BigInteger, fk="workflow_runs.id"),
    col("node_key"),
    col("node_type"),
    col("status"),
    col("input", JSONB, dict),
    col("output", JSONB, dict),
    col("error", default=""),
    col("tokens", Integer, 0),
    col("started_at", DateTime(timezone=True), now),
    col("finished_at", DateTime(timezone=True), nullable=True),
    timestamps=False,
    constraints=(UniqueConstraint("run_id", "node_key"),),
)
