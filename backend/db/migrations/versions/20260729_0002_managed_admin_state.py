"""Add monotonic managed-admin configuration state and FK helper indexes.

Revision ID: 20260729_0002
Revises: 20260729_0001
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import context, op


revision = "20260729_0002"
down_revision = "20260729_0001"
branch_labels = None
depends_on = None


def _create_managed_admin_state():
    op.create_table(
        "managed_admin_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "config_version",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "admin_user_id",
            name="uq_managed_admin_state_admin_user_id",
        ),
    )


def _index_names(inspector, table_name):
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade():
    if context.is_offline_mode():
        _create_managed_admin_state()
        op.create_index(
            "idx_diagnoses_crop",
            "diagnoses",
            ["crop_id"],
            unique=False,
        )
        op.create_index(
            "idx_follow_up_reminders_diagnosis",
            "follow_up_reminders",
            ["diagnosis_id"],
            unique=False,
        )
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "managed_admin_state" not in tables:
        _create_managed_admin_state()

    inspector = sa.inspect(bind)
    if (
        "diagnoses" in tables
        and "crop_id"
        in {column["name"] for column in inspector.get_columns("diagnoses")}
        and "idx_diagnoses_crop" not in _index_names(inspector, "diagnoses")
    ):
        op.create_index(
            "idx_diagnoses_crop",
            "diagnoses",
            ["crop_id"],
            unique=False,
        )
    if (
        "follow_up_reminders" in tables
        and "diagnosis_id"
        in {column["name"] for column in inspector.get_columns("follow_up_reminders")}
        and "idx_follow_up_reminders_diagnosis"
        not in _index_names(inspector, "follow_up_reminders")
    ):
        op.create_index(
            "idx_follow_up_reminders_diagnosis",
            "follow_up_reminders",
            ["diagnosis_id"],
            unique=False,
        )


def downgrade():
    raise RuntimeError(
        "The managed-admin migration is security critical and cannot be downgraded."
    )
