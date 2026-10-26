from sqlalchemy import BigInteger, Boolean, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import col, table

providers = table(
    "model_providers",
    col("code", String(32)),
    col("name"),
    col("base_url"),
    col("api_key", default=""),
    col("status", Integer, 1),
    constraints=(UniqueConstraint("code"),),
)

models = table(
    "model_configs",
    col("provider_id", BigInteger, fk="model_providers.id"),
    col("model_name"),
    col("alias"),
    col("type", default="chat"),
    col("context_window", Integer, 8192),
    col("max_output", Integer, 4096),
    col("input_price", Numeric(12, 6), 0),
    col("output_price", Numeric(12, 6), 0),
    col("priority", Integer, 100),
    col("capabilities", JSONB, list),
    col("is_default", Boolean, False),
    col("status", Integer, 1),
)
