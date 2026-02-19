"""Add render performance indexes

Revision ID: cc9d1f7f2a11
Revises: 3e14966c308e
Create Date: 2026-02-19 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "cc9d1f7f2a11"
down_revision = "3e14966c308e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_geo_set_member_geo_id_set_version_id "
        "ON gerrydb.geo_set_member (geo_id, set_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_geo_version_geo_id_valid_from "
        "ON gerrydb.geo_version (geo_id, valid_from DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_geo_version_geo_id_valid_to "
        "ON gerrydb.geo_version (geo_id, valid_to)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_column_value_geo_id_valid_from "
        "ON gerrydb.column_value (geo_id, valid_from DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_column_value_geo_id_valid_to "
        "ON gerrydb.column_value (geo_id, valid_to)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS gerrydb.ix_column_value_geo_id_valid_to")
    op.execute("DROP INDEX IF EXISTS gerrydb.ix_column_value_geo_id_valid_from")
    op.execute("DROP INDEX IF EXISTS gerrydb.ix_geo_version_geo_id_valid_to")
    op.execute("DROP INDEX IF EXISTS gerrydb.ix_geo_version_geo_id_valid_from")
    op.execute("DROP INDEX IF EXISTS gerrydb.ix_geo_set_member_geo_id_set_version_id")
