"""Initialize the application schema without overwriting incompatible tables."""

from alembic import op
from sqlalchemy import inspect

from app.models import metadata

revision = "001_python"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    incompatible_agents = "agents" in tables and "creator_id" not in {
        column["name"] for column in inspector.get_columns("agents")
    }
    if "schema_migrations" in tables or incompatible_agents:
        raise RuntimeError("检测到不兼容的数据库结构，请配置独立数据库；本次未更改已有表")
    metadata.create_all(connection)


def downgrade():
    metadata.drop_all(op.get_bind())
