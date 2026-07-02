"""Add view_render table

Revision ID: 3e14966c308e
Revises: a833eac3e58d
Create Date: 2023-04-17 20:40:21.434928

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "3e14966c308e"
down_revision = "a833eac3e58d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "view_render",
        sa.Column("render_id", sa.UUID(), nullable=False),
        sa.Column("view_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "RUNNING", "FAILED", "SUCCEEDED", name="viewrenderstatus"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["gerrydb.user.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["view_id"],
            ["gerrydb.view.view_id"],
        ),
        sa.PrimaryKeyConstraint("render_id"),
        schema="gerrydb",
    )


def downgrade() -> None:
    op.drop_table("view_render", schema="gerrydb")
