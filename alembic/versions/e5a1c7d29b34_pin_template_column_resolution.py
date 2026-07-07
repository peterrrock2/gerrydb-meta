"""Pin view-template column resolution at template-version creation.

Template members stored only ref_ids and resolved to columns at query
time, including at render time, so repointing a column reference (as
column materialization does) would retroactively change what existing
templates and views resolve. Each member row now carries the col_id the
ref resolved to at creation; data resolution reads the pin. Set-derived
members get their own hidden pin rows (direct = FALSE) so resolution
covers them without changing the authored member list; column sets
themselves stay unpinned.

Backfill uses each ref's current col_id, which is exactly what creation
would have pinned: no reference has ever been repointed before this
schema existed.

Revision ID: e5a1c7d29b34
Revises: b6e1d40c8f27
Create Date: 2026-07-07

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5a1c7d29b34"
down_revision = "b6e1d40c8f27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "view_template_column_member",
        sa.Column("col_id", sa.Integer(), nullable=True),
        schema="gerrydb",
    )
    op.add_column(
        "view_template_column_member",
        sa.Column("direct", sa.Boolean(), nullable=True),
        schema="gerrydb",
    )
    op.create_foreign_key(
        "view_template_column_member_col_id_fkey",
        "view_template_column_member",
        "column",
        ["col_id"],
        ["col_id"],
        source_schema="gerrydb",
        referent_schema="gerrydb",
    )
    op.execute(
        "UPDATE gerrydb.view_template_column_member m "
        "SET col_id = r.col_id, direct = TRUE "
        "FROM gerrydb.column_ref r WHERE r.ref_id = m.ref_id"
    )
    # Existing rows are all direct members; synthesize the hidden pin rows
    # for columns reached through column sets. Overlap between direct and
    # set-derived members is refused at template creation, so the conflict
    # clause is a guard, not an expected path.
    op.execute(
        "INSERT INTO gerrydb.view_template_column_member "
        '(template_version_id, ref_id, "order", col_id, direct) '
        'SELECT tsm.template_version_id, csm.ref_id, tsm."order", r.col_id, FALSE '
        "FROM gerrydb.view_template_column_set_member tsm "
        "JOIN gerrydb.column_set_member csm ON csm.set_id = tsm.set_id "
        "JOIN gerrydb.column_ref r ON r.ref_id = csm.ref_id "
        "ON CONFLICT (template_version_id, ref_id) DO NOTHING"
    )
    op.alter_column(
        "view_template_column_member", "col_id", nullable=False, schema="gerrydb"
    )
    op.alter_column(
        "view_template_column_member", "direct", nullable=False, schema="gerrydb"
    )


def downgrade() -> None:
    # Synthesized rows are indistinguishable once the flag is gone: remove
    # them while it still exists.
    op.execute("DELETE FROM gerrydb.view_template_column_member WHERE direct = FALSE")
    op.drop_constraint(
        "view_template_column_member_col_id_fkey",
        "view_template_column_member",
        schema="gerrydb",
    )
    op.drop_column("view_template_column_member", "direct", schema="gerrydb")
    op.drop_column("view_template_column_member", "col_id", schema="gerrydb")
