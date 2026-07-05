"""Index hygiene: drop write-tax indexes and the column_value col_id FK.

Drops, based on EXPLAIN evidence from the loaded national database (full
record: docs/baselines/2026-07-05_optimization-audit.md):

* The (geo_id, valid_from) twins on column_value and geo_version. Renders
  bitmap-scan the (geo_id, valid_to) twins; within a pruned partition,
  col_id-scoped probes use the primary key. Nothing consumes valid_from,
  and on column_value it cost ~74 GB and a third of per-insert index work.
* Ten single-column namespace_id/path indexes shadowed by their tables'
  UniqueConstraint(namespace_id, path), plus column_ref.path. Every
  lookup filters both columns, so the composite unique index serves them.
* The column_value -> column FK: LIST partition routing already rejects
  unknown col_ids (a row can only land in the partition created with its
  column) and columns are never deleted, so the RI trigger only re-checks
  an invariant the partition tree enforces, per row, across billions of
  bulk-load inserts.

Adds (view_id, created_at) / (graph_id, created_at) indexes for the
cached-render lookups: render history grows one row per render, forever.

Revision ID: a94d27e5c1f0
Revises: c81f3d5e7a29
Create Date: 2026-07-05

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a94d27e5c1f0"
down_revision = "c81f3d5e7a29"
branch_labels = None
depends_on = None

_SHADOWED = ("plan", "graph", "ensemble", "view_template", "view")


def upgrade() -> None:
    op.drop_index(
        "ix_column_value_geo_id_valid_from", table_name="column_value", schema="gerrydb"
    )
    op.drop_index(
        "ix_geo_version_geo_id_valid_from", table_name="geo_version", schema="gerrydb"
    )
    for table in _SHADOWED:
        op.drop_index(f"ix_gerrydb_{table}_namespace_id", table_name=table, schema="gerrydb")
        op.drop_index(f"ix_gerrydb_{table}_path", table_name=table, schema="gerrydb")
    op.drop_index("ix_gerrydb_column_ref_path", table_name="column_ref", schema="gerrydb")
    op.drop_constraint(
        "column_value_col_id_fkey", "column_value", schema="gerrydb", type_="foreignkey"
    )
    op.create_index(
        "ix_view_render_view_id_created_at",
        "view_render",
        ["view_id", "created_at"],
        schema="gerrydb",
    )
    op.create_index(
        "ix_graph_render_graph_id_created_at",
        "graph_render",
        ["graph_id", "created_at"],
        schema="gerrydb",
    )
    # geo_set_member is read-hot but small (~17M rows), so the default 20%
    # dead-tuple threshold lets millions of dead tuples accumulate before
    # autovacuum fires. Mirrors the after_create DDL in models.py.
    op.execute(
        "ALTER TABLE gerrydb.geo_set_member SET (autovacuum_vacuum_scale_factor = 0.05)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE gerrydb.geo_set_member RESET (autovacuum_vacuum_scale_factor)")
    op.drop_index("ix_graph_render_graph_id_created_at", table_name="graph_render", schema="gerrydb")
    op.drop_index("ix_view_render_view_id_created_at", table_name="view_render", schema="gerrydb")
    op.create_foreign_key(
        "column_value_col_id_fkey",
        "column_value",
        "column",
        ["col_id"],
        ["col_id"],
        source_schema="gerrydb",
        referent_schema="gerrydb",
    )
    op.create_index("ix_gerrydb_column_ref_path", "column_ref", ["path"], schema="gerrydb")
    for table in _SHADOWED:
        op.create_index(f"ix_gerrydb_{table}_path", table, ["path"], schema="gerrydb")
        op.create_index(
            f"ix_gerrydb_{table}_namespace_id", table, ["namespace_id"], schema="gerrydb"
        )
    op.create_index(
        "ix_geo_version_geo_id_valid_from",
        "geo_version",
        ["geo_id", "valid_from"],
        schema="gerrydb",
    )
    op.create_index(
        "ix_column_value_geo_id_valid_from",
        "column_value",
        ["geo_id", "valid_from"],
        schema="gerrydb",
    )
