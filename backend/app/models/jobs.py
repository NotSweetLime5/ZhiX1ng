from sqlalchemy import DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import col, table

jobs = table(
    "jobs",
    col("kind"),
    col("payload", JSONB),
    col("status", default="pending"),
    col("attempts", Integer, 0),
    col("error", default=""),
    col("lease_until", DateTime(timezone=True), nullable=True),
)
