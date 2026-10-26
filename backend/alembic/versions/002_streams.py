"""Redis Streams delivery metadata; PostgreSQL retains the transactional outbox."""

from alembic import op
from sqlalchemy import Column, Integer, Text, inspect, text

revision = "002_streams"
down_revision = "001_python"
branch_labels = None
depends_on = None


def upgrade():
    # 001 creates current metadata for fresh databases; upgrade existing installations too.
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("jobs")}
    if "queue_revision" not in columns:
        op.add_column("jobs", Column("queue_revision", Integer, nullable=False, server_default=text("0")))
    if "stream_id" not in columns:
        op.add_column("jobs", Column("stream_id", Text, nullable=False, server_default=""))


def downgrade():
    op.drop_column("jobs", "stream_id")
    op.drop_column("jobs", "queue_revision")
