"""Create districting plans.

Revision ID: 88f266906828
Revises: 6898afa765ca
Create Date: 2023-03-23 16:57:10.921907

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "88f266906828"
down_revision = "6898afa765ca"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("set_version_id", sa.Integer(), nullable=False),
        sa.Column("num_districts", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("districtr_id", sa.Text(), nullable=True),
        sa.Column("daves_id", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("plan_id"),
        sa.UniqueConstraint("namespace_id", "path"),
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_plan_namespace_id"),
        "plan",
        ["namespace_id"],
        unique=False,
        schema="gerrydb",
    )
    op.create_index(op.f("ix_gerrydb_plan_path"), "plan", ["path"], unique=False, schema="gerrydb")
    op.create_index(
        op.f("ix_gerrydb_plan_set_version_id"),
        "plan",
        ["set_version_id"],
        unique=False,
        schema="gerrydb",
    )
    op.create_table(
        "plan_assignment",
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("geo_id", sa.Integer(), nullable=False),
        sa.Column("assignment", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["geo_id"],
            ["gerrydb.geography.geo_id"],
        ),
        sa.PrimaryKeyConstraint("plan_id", "geo_id"),
        schema="gerrydb",
    )


def downgrade() -> None:
    op.drop_table("plan_assignment", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_plan_set_version_id"), table_name="plan", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_plan_path"), table_name="plan", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_plan_namespace_id"), table_name="plan", schema="gerrydb")
    op.drop_table("plan", schema="gerrydb")
