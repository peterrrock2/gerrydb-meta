"""Create geographic schema

Revision ID: f92609b1a9bd
Revises: d3b6ebaf041f
Create Date: 2023-03-22 14:05:07.271553

"""

import geoalchemy2
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f92609b1a9bd"
down_revision = "d3b6ebaf041f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geography",
        sa.Column("geo_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=False),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["meta_id"],
            ["gerrydb.meta.meta_id"],
        ),
        sa.ForeignKeyConstraint(
            ["namespace_id"],
            ["gerrydb.namespace.namespace_id"],
        ),
        sa.PrimaryKeyConstraint("geo_id"),
        schema="gerrydb",
    )
    op.create_table(
        "geo_import",
        sa.Column("import_id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.UUID(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=False),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["gerrydb.user.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["meta_id"],
            ["gerrydb.meta.meta_id"],
        ),
        sa.ForeignKeyConstraint(
            ["namespace_id"],
            ["gerrydb.namespace.namespace_id"],
        ),
        sa.PrimaryKeyConstraint("import_id"),
        schema="gerrydb",
    )
    op.create_index(
        op.f("ix_gerrydb_geo_import_uuid"),
        "geo_import",
        ["uuid"],
        unique=True,
        schema="gerrydb",
    )
    op.create_table(
        "geo_version",
        sa.Column("import_id", sa.Integer(), nullable=False),
        sa.Column("geo_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "geography",
            geoalchemy2.types.Geography(srid=4269, from_text="ST_GeogFromText", name="geography"),
            nullable=True,
        ),
        sa.Column(
            "internal_point",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4269,
                from_text="ST_GeogFromText",
                name="geography",
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["geo_id"],
            ["gerrydb.geography.geo_id"],
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["gerrydb.geo_import.import_id"],
        ),
        sa.PrimaryKeyConstraint("import_id", "geo_id"),
        schema="gerrydb",
    )
    op.create_table(
        "geo_layer",
        sa.Column("layer_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("namespace_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["meta_id"],
            ["gerrydb.meta.meta_id"],
        ),
        sa.ForeignKeyConstraint(
            ["namespace_id"],
            ["gerrydb.namespace.namespace_id"],
        ),
        sa.PrimaryKeyConstraint("layer_id"),
        sa.UniqueConstraint("path", "namespace_id"),
        schema="gerrydb",
    )
    op.create_table(
        "geo_hierarchy",
        sa.Column("parent_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("meta_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("parent_id <> child_id"),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["gerrydb.geography.geo_id"],
        ),
        sa.ForeignKeyConstraint(
            ["meta_id"],
            ["gerrydb.meta.meta_id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["gerrydb.geography.geo_id"],
        ),
        sa.PrimaryKeyConstraint("parent_id", "child_id"),
        schema="gerrydb",
    )
    op.create_table(
        "geo_set_version",
        sa.Column("set_version_id", sa.Integer(), nullable=False),
        sa.Column("layer_id", sa.Integer(), nullable=False),
        sa.Column("loc_id", sa.Integer(), nullable=False),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("set_version_id"),
        schema="gerrydb",
    )
    op.create_table(
        "geo_set_member",
        sa.Column("set_version_id", sa.Integer(), nullable=False),
        sa.Column("geo_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["geo_id"],
            ["gerrydb.geography.geo_id"],
        ),
        sa.ForeignKeyConstraint(
            ["set_version_id"],
            ["gerrydb.geo_set_version.set_version_id"],
        ),
        sa.PrimaryKeyConstraint("set_version_id", "geo_id"),
        schema="gerrydb",
    )


def downgrade() -> None:
    op.drop_table("geo_set_member", schema="gerrydb")
    op.drop_table("geo_set_version", schema="gerrydb")
    op.drop_table("geo_hierarchy", schema="gerrydb")
    op.drop_table("geo_layer", schema="gerrydb")
    op.drop_index(
        "idx_geo_version_internal_point",
        table_name="geo_version",
        schema="gerrydb",
        postgresql_using="gist",
    )
    op.drop_index(
        "idx_geo_version_geography",
        table_name="geo_version",
        schema="gerrydb",
        postgresql_using="gist",
    )
    op.drop_table("geo_version", schema="gerrydb")
    op.drop_index(op.f("ix_gerrydb_geo_import_uuid"), table_name="geo_import", schema="gerrydb")
    op.drop_table("geo_import", schema="gerrydb")
    op.drop_table("geography", schema="gerrydb")
