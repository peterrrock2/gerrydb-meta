"""Add num_geos to View

Revision ID: a833eac3e58d
Revises: 96d3750366ff
Create Date: 2023-04-11 10:28:48.058441

"""

from sqlalchemy import Column, ForeignKey, Integer

from alembic import op

# revision identifiers, used by Alembic.
revision = "a833eac3e58d"
down_revision = "96d3750366ff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("view", Column("num_geos", Integer(), nullable=False), schema="gerrydb")


def downgrade() -> None:
    op.drop_column("view", "num_geos", schema="gerrydb")
