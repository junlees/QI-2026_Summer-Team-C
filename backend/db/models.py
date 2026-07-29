"""Database engine and schema shared by SQLite demos and PostgreSQL.

Cloud Run normally requires PostgreSQL. The demo image explicitly opts into an
ephemeral SQLite database whose contents disappear with the container.
"""

import logging
import os
import threading
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


DB_PATH = os.path.join(os.path.dirname(__file__), "agrisage.db")
DEFAULT_EPHEMERAL_DB_PATH = "/tmp/agrisage-demo.db"
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_LOCK_KEY = 0x4167726953616765  # "AgriSage" as a stable int64 key
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"", "0", "false", "no", "off"}

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("public_id", String(36), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("email", String(320), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", String(20), nullable=False, server_default="user"),
    Column("certification", String(30), nullable=False, server_default="conventional"),
    Column("purpose", String(30), nullable=False, server_default="self_consumption"),
    Column("daily_limit", Integer, nullable=True, server_default="3"),
    Column("token_version", Integer, nullable=False, server_default="0"),
    UniqueConstraint("email", name="uq_users_email"),
    sqlite_autoincrement=True,
)

crops = Table(
    "crops",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("name", String(80), nullable=False),
    Column("emoji", String(16)),
    Column("color", String(16)),
    Column(
        "growing_environment", String(30), nullable=False, server_default="open_field"
    ),
    Column("purpose_override", String(30)),
    Column("harvest_date", String(10)),
    sqlite_autoincrement=True,
)

diagnoses = Table(
    "diagnoses",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE")),
    Column("crop_id", Integer, ForeignKey("crops.id", ondelete="SET NULL")),
    Column("class_id", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("status", String(30), nullable=False),
    Column("result_json", Text, nullable=False),
    Column("follow_up_status", String(30)),
    sqlite_autoincrement=True,
)

follow_up_reminders = Table(
    "follow_up_reminders",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "diagnosis_id",
        Integer,
        ForeignKey("diagnoses.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("target_date", String(10), nullable=False),
    Column("sent", Integer, nullable=False, server_default="0"),
    sqlite_autoincrement=True,
)

managed_admin_state = Table(
    "managed_admin_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "admin_user_id",
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    ),
    Column("config_version", BigInteger, nullable=False, server_default="0"),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

Index("uq_users_public_id", users.c.public_id, unique=True)
Index("idx_crops_user", crops.c.user_id)
Index("idx_diagnoses_user_created", diagnoses.c.user_id, diagnoses.c.created_at)
Index("idx_diagnoses_crop", diagnoses.c.crop_id)
Index(
    "idx_follow_up_reminders_diagnosis",
    follow_up_reminders.c.diagnosis_id,
)
Index("idx_users_email_lower", func.lower(users.c.email), unique=True)

_engine = None
_engine_url = None
_engine_lock = threading.Lock()


class DatabaseConfigurationError(RuntimeError):
    """Raised when production database configuration is unsafe or invalid."""


def _boolean_env(name):
    value = (os.environ.get(name) or "").strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise DatabaseConfigurationError(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off."
    )


def uses_ephemeral_cloud_run_sqlite():
    """Return whether this Cloud Run revision explicitly selected demo storage."""
    return bool(os.environ.get("K_SERVICE")) and _boolean_env("ALLOW_EPHEMERAL_SQLITE")


def _ephemeral_sqlite_url():
    path = Path(
        (os.environ.get("EPHEMERAL_SQLITE_PATH") or DEFAULT_EPHEMERAL_DB_PATH).strip()
    )
    if not path.is_absolute():
        raise DatabaseConfigurationError(
            "EPHEMERAL_SQLITE_PATH must be an absolute path."
        )
    return f"sqlite+pysqlite:///{path}"


def get_database_url():
    """Return the configured database URL or the explicit demo SQLite URL."""
    configured = (os.environ.get("DATABASE_URL") or "").strip()
    on_cloud_run = bool(os.environ.get("K_SERVICE"))

    # Demo mode deliberately wins over DATABASE_URL. This prevents a stale
    # Cloud SQL secret/reference from breaking a disposable demo revision.
    # Set ALLOW_EPHEMERAL_SQLITE=false to opt back into PostgreSQL.
    if uses_ephemeral_cloud_run_sqlite():
        return _ephemeral_sqlite_url()

    if not configured:
        if on_cloud_run:
            raise DatabaseConfigurationError(
                "DATABASE_URL must be set to PostgreSQL on Cloud Run unless "
                "ALLOW_EPHEMERAL_SQLITE=true."
            )
        return f"sqlite+pysqlite:///{Path(DB_PATH).resolve()}"

    if configured.startswith("postgres://"):
        configured = "postgresql+psycopg://" + configured[len("postgres://") :]
    elif configured.startswith("postgresql://"):
        configured = "postgresql+psycopg://" + configured[len("postgresql://") :]

    try:
        url = make_url(configured)
    except (TypeError, ValueError) as exc:
        raise DatabaseConfigurationError(
            "DATABASE_URL is not a valid database URL."
        ) from exc

    if on_cloud_run and url.get_backend_name() != "postgresql":
        raise DatabaseConfigurationError(
            "Cloud Run SQLite requires ALLOW_EPHEMERAL_SQLITE=true."
        )
    if url.get_backend_name() not in {"postgresql", "sqlite"}:
        raise DatabaseConfigurationError(
            "Only PostgreSQL and local SQLite are supported."
        )
    if (
        url.get_backend_name() == "postgresql"
        and url.drivername != "postgresql+psycopg"
    ):
        raise DatabaseConfigurationError(
            "PostgreSQL DATABASE_URL must use the psycopg3 driver."
        )

    return url.render_as_string(hide_password=False)


def validate_config():
    """Validate database configuration without opening a connection."""
    get_database_url()
    if uses_ephemeral_cloud_run_sqlite():
        logging.getLogger(__name__).warning(
            "Cloud Run demo mode is using ephemeral SQLite at %s. Accounts, "
            "sessions, crops, and diagnoses disappear when the instance stops.",
            Path(os.environ.get("EPHEMERAL_SQLITE_PATH") or DEFAULT_EPHEMERAL_DB_PATH),
        )


def _configure_sqlite(engine):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
        finally:
            cursor.close()


def get_engine():
    """Return the process-wide SQLAlchemy engine for the current DATABASE_URL."""
    global _engine, _engine_url

    url = get_database_url()
    if _engine is not None and _engine_url == url:
        return _engine

    with _engine_lock:
        if _engine is not None and _engine_url == url:
            return _engine
        if _engine is not None:
            _engine.dispose()

        parsed = make_url(url)
        kwargs = {"pool_pre_ping": True}
        if parsed.get_backend_name() == "sqlite":
            kwargs["connect_args"] = {"timeout": 10}
        else:
            # At the deployment default of ten Cloud Run instances this caps
            # the application at 30 PostgreSQL connections.
            kwargs.update({"pool_size": 2, "max_overflow": 1, "pool_timeout": 10})

        engine = create_engine(url, **kwargs)
        if parsed.get_backend_name() == "sqlite":
            _configure_sqlite(engine)

        _engine = engine
        _engine_url = url
        return engine


def reset_engine():
    """Dispose the cached engine. Intended for tests and controlled reconfiguration."""
    global _engine, _engine_url
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _engine_url = None


def _alembic_config(connection):
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    return config


def _foreign_key_targets(inspector, table_name):
    return {
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
            ((foreign_key.get("options") or {}).get("ondelete") or "").upper(),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }


def _validate_postgres_schema(connection):
    """Fail closed when an existing PostgreSQL database has an unsafe shape."""
    inspector = inspect(connection)
    required_tables = {
        "users",
        "crops",
        "diagnoses",
        "follow_up_reminders",
        "managed_admin_state",
        "alembic_version",
    }
    missing_tables = required_tables - set(inspector.get_table_names())
    if missing_tables:
        raise DatabaseConfigurationError(
            "PostgreSQL schema is incomplete; missing tables: "
            + ", ".join(sorted(missing_tables))
        )

    columns = {
        table_name: {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        for table_name in required_tables - {"alembic_version"}
    }
    required_columns = {
        "users": {"id", "public_id", "email", "password_hash", "role", "token_version"},
        "crops": {"id", "user_id"},
        "diagnoses": {"id", "user_id", "crop_id", "created_at"},
        "follow_up_reminders": {"id", "diagnosis_id"},
        "managed_admin_state": {"id", "admin_user_id", "config_version"},
    }
    for table_name, expected in required_columns.items():
        missing = expected - set(columns[table_name])
        if missing:
            raise DatabaseConfigurationError(
                f"PostgreSQL table {table_name} is missing required columns: "
                + ", ".join(sorted(missing))
            )

    if columns["users"]["public_id"]["nullable"]:
        raise DatabaseConfigurationError("PostgreSQL users.public_id must be NOT NULL.")
    integer_columns = (
        ("users", "id"),
        ("users", "token_version"),
        ("crops", "user_id"),
        ("diagnoses", "user_id"),
        ("diagnoses", "crop_id"),
        ("follow_up_reminders", "diagnosis_id"),
        ("managed_admin_state", "admin_user_id"),
        ("managed_admin_state", "config_version"),
    )
    for table_name, column_name in integer_columns:
        if not isinstance(columns[table_name][column_name]["type"], Integer):
            raise DatabaseConfigurationError(
                f"PostgreSQL {table_name}.{column_name} must be an integer type."
            )

    required_foreign_keys = {
        "crops": {(("user_id",), "users", ("id",), "CASCADE")},
        "diagnoses": {
            (("user_id",), "users", ("id",), "CASCADE"),
            (("crop_id",), "crops", ("id",), "SET NULL"),
        },
        "follow_up_reminders": {(("diagnosis_id",), "diagnoses", ("id",), "CASCADE")},
        "managed_admin_state": {(("admin_user_id",), "users", ("id",), "SET NULL")},
    }
    for table_name, expected in required_foreign_keys.items():
        missing = expected - _foreign_key_targets(inspector, table_name)
        if missing:
            raise DatabaseConfigurationError(
                f"PostgreSQL table {table_name} is missing required foreign keys."
            )

    required_indexes = {
        "users": {"uq_users_public_id", "idx_users_email_lower"},
        "crops": {"idx_crops_user"},
        "diagnoses": {"idx_diagnoses_user_created", "idx_diagnoses_crop"},
        "follow_up_reminders": {"idx_follow_up_reminders_diagnosis"},
    }
    for table_name, expected in required_indexes.items():
        present = {index["name"] for index in inspector.get_indexes(table_name)}
        missing = expected - present
        if missing:
            raise DatabaseConfigurationError(
                f"PostgreSQL table {table_name} is missing required indexes: "
                + ", ".join(sorted(missing))
            )


def init_db():
    """Upgrade the configured database to the latest schema and verify access."""
    engine = get_engine()
    try:
        with engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET LOCAL lock_timeout = '15s'"))
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": _MIGRATION_LOCK_KEY},
                )
            command.upgrade(_alembic_config(connection), "head")
            if connection.dialect.name == "postgresql":
                _validate_postgres_schema(connection)
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Preserve the original driver exception and fail application startup.
        raise
