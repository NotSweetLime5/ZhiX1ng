"""Python schema; initialize a separate database from the legacy Go schema."""

from alembic import op
from app.models import metadata

revision = "001_python"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    metadata.drop_all(op.get_bind())
