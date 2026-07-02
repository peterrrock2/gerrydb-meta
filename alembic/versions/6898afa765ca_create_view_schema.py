"""Create view schema

Revision ID: 6898afa765ca
Revises: 8dd630f55d05
Create Date: 2023-03-21 16:54:56.498038

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "6898afa765ca"
down_revision = "8dd630f55d05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "etag",
        sa.Column("etag_id", sa.Integer(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=True),
        sa.Column("table", sa.Text(), nullable=False),
        sa.Column("etag", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["namespace_id"],
            ["gerrydb.namespace.namespace_id"],
        ),
        sa.PrimaryKeyConstraint("etag_id"),
        sa.UniqueConstraint("namespace_id", "table"),
        schema="gerrydb",
    )
    op.create_table(
        "view_template",
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["meta_id"],
            ["gerrydb.meta.meta_id"],
        ),
        sa.ForeignKeyConstraint(
            ["namespace_id"],
            ["gerrydb.namespace.namespace_id"],
        ),
        sa.PrimaryKeyConstraint("template_id"),
        sa.UniqueConstraint("namespace_id", "path"),
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_view_template_namespace_id"),
        "view_template",
        ["namespace_id"],
        unique=False,
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_view_template_path"),
        "view_template",
        ["path"],
        unique=False,
        schema="gerrydb",
    )
    op.create_table(
        "view_template_version",
        sa.Column("template_version_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["meta_id"],
            ["gerrydb.meta.meta_id"],
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["gerrydb.view_template.template_id"],
        ),
        sa.PrimaryKeyConstraint("template_version_id"),
        schema="gerrydb",
    )
    op.create_table(
        "view",
        sa.Column("view_id", sa.Integer(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("template_version_id", sa.Integer(), nullable=False),
        sa.Column("loc_id", sa.Integer(), nullable=False),
        sa.Column("layer_id", sa.Integer(), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("proj", sa.Text(), nullable=True),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["layer_id"],
            ["gerrydb.geo_layer.layer_id"],
        ),
        sa.ForeignKeyConstraint(
            ["loc_id"],
            ["gerrydb.locality.loc_id"],
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
            ["template_id"],
            ["gerrydb.view_template.template_id"],
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["gerrydb.view_template_version.template_version_id"],
        ),
        sa.PrimaryKeyConstraint("view_id"),
        sa.UniqueConstraint("namespace_id", "path"),
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_view_namespace_id"),
        "view",
        ["namespace_id"],
        unique=False,
        schema="gerrydb",
    )
    op.create_index(op.f("ix_gerrydb_view_path"), "view", ["path"], unique=False, schema="gerrydb")
    op.create_table(
        "view_template_column_member",
        sa.Column("template_version_id", sa.Integer(), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ref_id"],
            ["gerrydb.column_ref.ref_id"],
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["gerrydb.view_template_version.template_version_id"],
        ),
        sa.PrimaryKeyConstraint("template_version_id", "ref_id"),
        schema="gerrydb",
    )
    op.create_table(
        "view_template_column_set_member",
        sa.Column("template_version_id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["set_id"],
            ["gerrydb.column_set.set_id"],
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["gerrydb.view_template_version.template_version_id"],
        ),
        sa.PrimaryKeyConstraint("template_version_id", "set_id"),
        schema="gerrydb",
    )


def downgrade() -> None:
    op.drop_table("view_template_column_set_member", schema="gerrydb")
    op.drop_table("view_template_column_member", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_view_path"), table_name="view", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_view_namespace_id"), table_name="view", schema="gerrydb")
    op.drop_table("view", schema="gerrydb")
    op.drop_table("view_template_version", schema="gerrydb")

    op.drop_index(
        op.f("ix_gerrydb_view_template_path"),
        table_name="view_template",
        schema="gerrydb",
    )
    op.drop_index(
        op.f("ix_gerrydb_view_template_namespace_id"),
        table_name="view_template",
        schema="gerrydb",
    )
    op.drop_table("view_template", schema="gerrydb")
    op.drop_table("etag", schema="gerrydb")
