"""Add content fingerprints to column_value_count.

Two signed 64-bit XOR accumulators per (column, set version): the
order-independent multiset hash of the current (geo path, value) pairs
(see gerrydb_meta/value_hash.py). Written incrementally by the value
writers; NULL means not yet computed (e.g. pre-existing rows before the
backfill), which simply disables duplicate detection for that pair.

Revision ID: c81f3d5e7a29
Revises: 4f2bd11c9e83
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c81f3d5e7a29"
down_revision = "4f2bd11c9e83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "column_value_count",
        sa.Column("value_hash_hi", sa.BigInteger(), nullable=True),
        schema="gerrydb",
    )
    op.add_column(
        "column_value_count",
        sa.Column("value_hash_lo", sa.BigInteger(), nullable=True),
        schema="gerrydb",
    )


def downgrade() -> None:
    op.drop_column("column_value_count", "value_hash_hi", schema="gerrydb")
    op.drop_column("column_value_count", "value_hash_lo", schema="gerrydb")
