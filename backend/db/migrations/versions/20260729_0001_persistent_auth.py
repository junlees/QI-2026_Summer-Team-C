"""Create the persistent application schema and revocable UUID authentication.

Revision ID: 20260729_0001
Revises:
Create Date: 2026-07-29

This baseline deliberately contains a frozen schema definition. Do not import
the live application metadata here: later model changes belong in later
revisions so a fresh database always replays the same migration history.
"""

import uuid

import sqlalchemy as sa
from alembic import context, op


revision = "20260729_0001"
down_revision = None
branch_labels = None
depends_on = None


def _column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector, table_name):
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    indexes.update(
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    )
    return indexes


def _create_users():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=20),
            server_default="user",
            nullable=False,
        ),
        sa.Column(
            "certification",
            sa.String(length=30),
            server_default="conventional",
            nullable=False,
        ),
        sa.Column(
            "purpose",
            sa.String(length=30),
            server_default="self_consumption",
            nullable=False,
        ),
        sa.Column(
            "daily_limit",
            sa.Integer(),
            server_default="3",
            nullable=True,
        ),
        sa.Column(
            "token_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sqlite_autoincrement=True,
    )
    op.create_index("uq_users_public_id", "users", ["public_id"], unique=True)
    op.create_index(
        "idx_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def _create_crops():
    op.create_table(
        "crops",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column(
            "growing_environment",
            sa.String(length=30),
            server_default="open_field",
            nullable=False,
        ),
        sa.Column("purpose_override", sa.String(length=30), nullable=True),
        sa.Column("harvest_date", sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("idx_crops_user", "crops", ["user_id"], unique=False)


def _create_diagnoses():
    op.create_table(
        "diagnoses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("crop_id", sa.Integer(), nullable=True),
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("follow_up_status", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["crop_id"], ["crops.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "idx_diagnoses_user_created",
        "diagnoses",
        ["user_id", "created_at"],
        unique=False,
    )


def _create_follow_up_reminders():
    op.create_table(
        "follow_up_reminders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("diagnosis_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.String(length=10), nullable=False),
        sa.Column("sent", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["diagnosis_id"],
            ["diagnoses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )


def _create_fresh_schema():
    _create_users()
    _create_crops()
    _create_diagnoses()
    _create_follow_up_reminders()


def _upgrade_existing_users(bind, inspector):
    columns = _column_names(inspector, "users")
    with op.batch_alter_table("users") as batch:
        if "public_id" not in columns:
            batch.add_column(
                sa.Column("public_id", sa.String(length=36), nullable=True)
            )
        if "token_version" not in columns:
            batch.add_column(
                sa.Column(
                    "token_version",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )

    users_table = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("public_id", sa.String(length=36)),
    )
    missing = bind.execute(
        sa.select(users_table.c.id).where(users_table.c.public_id.is_(None))
    ).scalars()
    for user_id in missing:
        bind.execute(
            sa.update(users_table)
            .where(users_table.c.id == user_id)
            .values(public_id=str(uuid.uuid4()))
        )

    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "users")
    if "uq_users_public_id" not in indexes:
        op.create_index("uq_users_public_id", "users", ["public_id"], unique=True)
    if "idx_users_email_lower" not in indexes:
        op.create_index(
            "idx_users_email_lower",
            "users",
            [sa.text("lower(email)")],
            unique=True,
        )

    # PostgreSQL production is strict. SQLite's legacy demo table keeps its
    # original declaration to avoid a destructive table rebuild, but every
    # existing row is backfilled and every new application write is non-null.
    if bind.dialect.name == "postgresql":
        op.alter_column("users", "public_id", nullable=False)


def _upgrade_existing_crops(bind, inspector):
    columns = _column_names(inspector, "crops")
    if "user_id" not in columns:
        return
    if "idx_crops_user" not in _index_names(inspector, "crops"):
        op.create_index("idx_crops_user", "crops", ["user_id"], unique=False)


def _upgrade_existing_diagnoses(bind, inspector):
    columns = _column_names(inspector, "diagnoses")
    with op.batch_alter_table("diagnoses") as batch:
        if "user_id" not in columns:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        if "follow_up_status" not in columns:
            batch.add_column(
                sa.Column("follow_up_status", sa.String(length=30), nullable=True)
            )

    inspector = sa.inspect(bind)
    columns = _column_names(inspector, "diagnoses")
    if {
        "user_id",
        "created_at",
    } <= columns and "idx_diagnoses_user_created" not in _index_names(
        inspector, "diagnoses"
    ):
        op.create_index(
            "idx_diagnoses_user_created",
            "diagnoses",
            ["user_id", "created_at"],
            unique=False,
        )


def upgrade():
    if context.is_offline_mode():
        _create_fresh_schema()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "users" not in existing_tables:
        _create_users()
    else:
        _upgrade_existing_users(bind, inspector)

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "crops" not in existing_tables:
        _create_crops()
    else:
        _upgrade_existing_crops(bind, inspector)

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "diagnoses" not in existing_tables:
        _create_diagnoses()
    else:
        _upgrade_existing_diagnoses(bind, inspector)

    inspector = sa.inspect(bind)
    if "follow_up_reminders" not in set(inspector.get_table_names()):
        _create_follow_up_reminders()


def downgrade():
    raise RuntimeError(
        "The persistent-auth migration is security critical and cannot be downgraded."
    )
