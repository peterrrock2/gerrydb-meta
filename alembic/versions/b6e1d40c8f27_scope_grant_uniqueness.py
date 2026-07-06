"""Correct the uniqueness key on scope grants.

The old declarations listed the "scope" column twice (Postgres collapsed
the duplicate at create time) and omitted namespace_group, so a grant
scoped to a namespace group was not distinguishable from other grants on
the same (user, scope, namespace). Both nullable key columns also used
default UNIQUE NULL semantics, letting global grants (both NULL)
duplicate without bound. The new constraints key the full grant shape
with NULLS NOT DISTINCT.

Revision ID: b6e1d40c8f27
Revises: a94d27e5c1f0
Create Date: 2026-07-05

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b6e1d40c8f27"
down_revision = "a94d27e5c1f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("user_scope_user_id_scope_namespace_id_key", "user_scope", schema="gerrydb")
    op.create_unique_constraint(
        "uq_user_scope_grant",
        "user_scope",
        ["user_id", "scope", "namespace_group", "namespace_id"],
        schema="gerrydb",
        postgresql_nulls_not_distinct=True,
    )
    op.drop_constraint(
        "user_group_scope_group_id_scope_namespace_id_key", "user_group_scope", schema="gerrydb"
    )
    op.create_unique_constraint(
        "uq_user_group_scope_grant",
        "user_group_scope",
        ["group_id", "scope", "namespace_group", "namespace_id"],
        schema="gerrydb",
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_group_scope_grant", "user_group_scope", schema="gerrydb")
    op.create_unique_constraint(
        "user_group_scope_group_id_scope_namespace_id_key",
        "user_group_scope",
        ["group_id", "scope", "namespace_id"],
        schema="gerrydb",
    )
    op.drop_constraint("uq_user_scope_grant", "user_scope", schema="gerrydb")
    op.create_unique_constraint(
        "user_scope_user_id_scope_namespace_id_key",
        "user_scope",
        ["user_id", "scope", "namespace_id"],
        schema="gerrydb",
    )
