"""Create dual graphs.

Revision ID: abd59c616667
Revises: 88f266906828
Create Date: 2023-03-23 16:59:16.924503

"""

import sqlalchemy as sa
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "abd59c616667"
down_revision = "88f266906828"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph",
        sa.Column("graph_id", sa.Integer(), nullable=False),
        sa.Column("set_version_id", sa.Integer(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("proj", sa.Text(), nullable=True),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
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
            ["set_version_id"],
            ["gerrydb.geo_set_version.set_version_id"],
        ),
        sa.PrimaryKeyConstraint("graph_id"),
        sa.UniqueConstraint("namespace_id", "path"),
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_graph_namespace_id"),
        "graph",
        ["namespace_id"],
        unique=False,
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_graph_path"),
        "graph",
        ["path"],
        unique=False,
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_graph_set_version_id"),
        "graph",
        ["set_version_id"],
        unique=False,
        schema="gerrydb",
    )
    op.create_table(
        "graph_edge",
        sa.Column("graph_id", sa.Integer(), nullable=False),
        sa.Column("geo_id_1", sa.Integer(), nullable=False),
        sa.Column("geo_id_2", sa.Integer(), nullable=False),
        sa.Column("weights", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["graph_id"],
            ["gerrydb.graph.graph_id"],
        ),
        sa.ForeignKeyConstraint(
            ["geo_id_1"],
            ["gerrydb.geography.geo_id"],
        ),
        sa.ForeignKeyConstraint(
            ["geo_id_2"],
            ["gerrydb.geography.geo_id"],
        ),
        sa.PrimaryKeyConstraint("graph_id", "geo_id_1", "geo_id_2"),
        schema="gerrydb",
    )
    op.add_column(
        "view",
        Column("graph_id", Integer(), ForeignKey("graph.graph_id")),
        schema="gerrydb",
    )


def downgrade() -> None:
    op.drop_column("view", "graph_id", schema="gerrydb")
    op.drop_table("graph_edge", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_graph_set_version_id"), table_name="graph", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_graph_path"), table_name="graph", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_graph_namespace_id"), table_name="graph", schema="gerrydb")
    op.drop_table("graph", schema="gerrydb")
