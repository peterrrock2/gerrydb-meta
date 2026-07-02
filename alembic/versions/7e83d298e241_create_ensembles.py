"""Create ensemble metadata.

Revision ID: 7e83d298e241
Revises: abd59c616667
Create Date: 2023-03-23 17:02:22.588999

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "7e83d298e241"
down_revision = "abd59c616667"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ensemble",
        sa.Column("ensemble_id", sa.Integer(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("graph_id", sa.Integer(), nullable=False),
        sa.Column("blob_hash", sa.LargeBinary(), nullable=False),
        sa.Column("blob_url", sa.String(length=2048), nullable=False),
        sa.Column("pop_col_id", sa.Integer(), nullable=True),
        sa.Column("seed_plan_id", sa.Integer(), nullable=True),
        sa.Column("num_districts", sa.Integer(), nullable=False),
        sa.Column("num_plans", sa.Integer(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["graph_id"],
            ["gerrydb.graph.graph_id"],
        ),
        sa.ForeignKeyConstraint(
            ["meta_id"],
            ["gerrydb.meta.meta_id"],
        ),
        sa.ForeignKeyConstraint(
            ["namespace_id"],
            ["gerrydb.namespace.namespace_id"],
        ),
        sa.ForeignKeyConstraint(
            ["pop_col_id"],
            ["gerrydb.column.col_id"],
        ),
        sa.ForeignKeyConstraint(
            ["seed_plan_id"],
            ["gerrydb.plan.plan_id"],
        ),
        sa.PrimaryKeyConstraint("ensemble_id"),
        sa.UniqueConstraint("namespace_id", "path"),
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_ensemble_graph_id"),
        "ensemble",
        ["graph_id"],
        unique=False,
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_ensemble_namespace_id"),
        "ensemble",
        ["namespace_id"],
        unique=False,
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_ensemble_path"),
        "ensemble",
        ["path"],
        unique=False,
        schema="gerrydb",
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_gerrydb_ensemble_path"), table_name="ensemble", schema="gerrydb")
    op.drop_index(
        op.f("ix_gerrydb_ensemble_namespace_id"),
        table_name="ensemble",
        schema="gerrydb",
    )
    op.drop_index(op.f("ix_gerrydb_ensemble_graph_id"), table_name="ensemble", schema="gerrydb")
    op.drop_table("ensemble", schema="gerrydb")
