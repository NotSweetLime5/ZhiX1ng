"""Python schema; initialize a separate database from the legacy Go schema."""

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
    legacy_agents = "agents" in tables and "creator_id" not in {
        column["name"] for column in inspector.get_columns("agents")
    }
    if "schema_migrations" in tables or legacy_agents:
        raise RuntimeError("检测到原版 Go 数据库，请为 Python 配置独立数据库；本次未转换旧表结构")
    metadata.create_all(connection)


def downgrade():
    metadata.drop_all(op.get_bind())
