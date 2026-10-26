from sqlalchemy import Integer, String, UniqueConstraint

from app.models.base import col, table

users = table(
    "users",
    col("username", String(64)),
    col("email", String(128)),
    col("password_hash"),
    col("role", default="user"),
    col("avatar_url", default=""),
    col("status", Integer, 1),
    constraints=(UniqueConstraint("username"), UniqueConstraint("email")),
)
