"""Create the sandbox execution audit table."""

from alembic import op

from app.models import sandbox_executions

revision = "003_sandbox_audit"
down_revision = "002_streams"
branch_labels = None
depends_on = None


def upgrade():
    sandbox_executions.create(op.get_bind(), checkfirst=True)


def downgrade():
    sandbox_executions.drop(op.get_bind(), checkfirst=True)
