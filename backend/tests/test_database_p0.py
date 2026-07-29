import datetime
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from alembic import command
from sqlalchemy import func, inspect, select


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db import crud, models  # noqa: E402


class DatabaseConfigurationTests(unittest.TestCase):
    def tearDown(self):
        models.reset_engine()

    def test_cloud_run_requires_postgresql(self):
        with mock.patch.dict(
            os.environ,
            {
                "K_SERVICE": "agrisage",
                "ALLOW_EPHEMERAL_SQLITE": "false",
            },
            clear=False,
        ):
            os.environ.pop("DATABASE_URL", None)
            with self.assertRaises(models.DatabaseConfigurationError):
                models.get_database_url()

            os.environ["DATABASE_URL"] = "sqlite+pysqlite:////tmp/unsafe.db"
            with self.assertRaises(models.DatabaseConfigurationError):
                models.get_database_url()

    def test_cloud_run_demo_mode_uses_disposable_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "cloud-run-demo.db")
            with mock.patch.dict(
                os.environ,
                {
                    "K_SERVICE": "agrisage",
                    "ALLOW_EPHEMERAL_SQLITE": "true",
                    "EPHEMERAL_SQLITE_PATH": database_path,
                    # Demo mode intentionally ignores a stale production URL.
                    "DATABASE_URL": (
                        "postgresql://user:password@/agrisage"
                        "?host=/cloudsql/PROJECT:REGION:INSTANCE"
                    ),
                },
                clear=False,
            ):
                models.reset_engine()
                self.assertEqual(
                    models.get_database_url(),
                    f"sqlite+pysqlite:///{database_path}",
                )
                models.init_db()
                self.assertIn("users", inspect(models.get_engine()).get_table_names())
                models.reset_engine()

    def test_cloud_run_demo_mode_rejects_invalid_flag(self):
        with mock.patch.dict(
            os.environ,
            {
                "K_SERVICE": "agrisage",
                "ALLOW_EPHEMERAL_SQLITE": "sometimes",
            },
            clear=False,
        ):
            with self.assertRaises(models.DatabaseConfigurationError):
                models.get_database_url()

    def test_postgres_url_is_normalized_for_psycopg3(self):
        with mock.patch.dict(
            os.environ,
            {
                "K_SERVICE": "agrisage",
                "ALLOW_EPHEMERAL_SQLITE": "false",
                "DATABASE_URL": "postgresql://user:p%40ss@db.example/agrisage",
            },
            clear=False,
        ):
            normalized = models.get_database_url()
            self.assertTrue(normalized.startswith("postgresql+psycopg://"))
            self.assertIn("p%40ss", normalized)
            self.assertNotIn("***", normalized)

    def test_postgres_rejects_non_psycopg3_driver(self):
        with mock.patch.dict(
            os.environ,
            {
                "K_SERVICE": "",
                "ALLOW_EPHEMERAL_SQLITE": "false",
                "DATABASE_URL": "postgresql+psycopg2://user:password@db/agrisage",
            },
            clear=False,
        ):
            with self.assertRaises(models.DatabaseConfigurationError):
                models.get_database_url()


class SqliteMigrationAndCrudTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "test.db")
        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": f"sqlite+pysqlite:///{self.database_path}",
                "K_SERVICE": "",
            },
            clear=False,
        )
        self.env_patch.start()
        models.reset_engine()
        models.init_db()

    def tearDown(self):
        models.reset_engine()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def _create_user(self, email="user@example.com"):
        return crud.create_user(
            email,
            "password-hash",
            "conventional",
            "self_consumption",
        )

    def test_user_gets_stable_uuid_and_case_insensitive_email_uniqueness(self):
        user = self._create_user("USER@Example.com")

        self.assertEqual(str(uuid.UUID(user["public_id"])), user["public_id"])
        self.assertEqual(user["token_version"], 0)
        self.assertEqual(
            crud.get_user_by_email("uSeR@example.COM")["id"],
            user["id"],
        )
        with self.assertRaises(crud.DuplicateEmailError):
            self._create_user("user@example.com")

    def test_managed_admin_versions_are_monotonic_and_idempotent(self):
        user = self._create_user()

        first = crud.apply_managed_admin_config(user["email"], "first-hash", 1)
        rotated = crud.get_user_by_id(user["id"])
        self.assertEqual(first["status"], "applied")
        self.assertEqual(rotated["role"], "admin")
        self.assertEqual(rotated["token_version"], 1)
        self.assertEqual(rotated["password_hash"], "first-hash")

        current = crud.apply_managed_admin_config(
            user["email"],
            "must-not-be-written",
            1,
        )
        unchanged = crud.get_user_by_id(user["id"])
        self.assertEqual(current["status"], "current")
        self.assertEqual(unchanged["token_version"], 1)
        self.assertEqual(unchanged["password_hash"], "first-hash")

        crud.apply_managed_admin_config(user["email"], "second-hash", 2)
        self.assertEqual(crud.get_user_by_id(user["id"])["token_version"], 2)

        stale = crud.apply_managed_admin_config(user["email"], "first-hash", 1)
        newest = crud.get_user_by_id(user["id"])
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(newest["password_hash"], "second-hash")
        self.assertEqual(newest["token_version"], 2)

    def test_admin_id_rotation_demotes_and_revokes_previous_admins(self):
        first = self._create_user("first-admin@example.com")
        second = self._create_user("second-admin@example.com")
        crud.apply_managed_admin_config(first["email"], "first-hash", 1)

        crud.apply_managed_admin_config(second["email"], "second-hash", 2)

        former = crud.get_user_by_id(first["id"])
        current = crud.get_user_by_id(second["id"])
        self.assertEqual(former["role"], "user")
        self.assertEqual(former["daily_limit"], 3)
        self.assertEqual(former["token_version"], 2)
        self.assertEqual(current["role"], "admin")
        self.assertEqual(current["token_version"], 1)
        with models.get_engine().connect() as connection:
            admin_count = connection.execute(
                select(func.count())
                .select_from(models.users)
                .where(models.users.c.role == "admin")
            ).scalar_one()
        self.assertEqual(admin_count, 1)

    def test_admin_api_identifiers_are_public_uuids(self):
        user = self._create_user()

        listed = crud.admin_list_users(crud.kst_today_start_utc())
        self.assertEqual(listed[0]["id"], user["public_id"])
        self.assertTrue(crud.set_daily_limit(user["public_id"], 9))
        self.assertEqual(crud.get_user_by_id(user["id"])["daily_limit"], 9)

    def test_crop_diagnosis_and_reminder_share_transactional_schema(self):
        user = self._create_user()
        crop = crud.create_crop(
            user["id"],
            "Apple",
            "🍎",
            "#3f7d20",
            "open_field",
            None,
            "2026-08-15",
        )
        diagnosis_id = crud.save_diagnosis(
            crop_id=crop["id"],
            class_id="Apple___Apple_scab",
            confidence=91.2,
            status="diagnosed",
            result={"status": "diagnosed", "class_id": "Apple___Apple_scab"},
            follow_up_target_date="2026-07-01",
            user_id=user["id"],
        )

        self.assertEqual(
            crud.get_diagnosis(user["id"], diagnosis_id)["class_id"],
            "Apple___Apple_scab",
        )
        self.assertEqual(
            crud.count_diagnoses_since(
                user["id"],
                datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc),
            ),
            1,
        )
        self.assertEqual(
            crud.get_due_follow_ups("2026-07-29")[0]["diagnosis_id"],
            diagnosis_id,
        )
        self.assertTrue(crud.set_follow_up_status(user["id"], diagnosis_id, "resolved"))

        self.assertTrue(crud.delete_crop(user["id"], crop["id"]))
        history = crud.get_history(user["id"])
        self.assertEqual(len(history), 1)
        self.assertIsNone(history[0]["crop_name"])


class LegacySqliteMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "legacy.db")
        connection = sqlite3.connect(self.database_path)
        try:
            connection.executescript(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    certification TEXT NOT NULL DEFAULT 'conventional',
                    purpose TEXT NOT NULL DEFAULT 'self_consumption',
                    daily_limit INTEGER DEFAULT 3
                );
                INSERT INTO users (email, password_hash)
                VALUES ('legacy@example.com', 'legacy-hash');
                """
            )
            connection.commit()
        finally:
            connection.close()

        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": f"sqlite+pysqlite:///{self.database_path}",
                "K_SERVICE": "",
            },
            clear=False,
        )
        self.env_patch.start()
        models.reset_engine()

    def tearDown(self):
        models.reset_engine()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_legacy_user_is_backfilled_once(self):
        models.init_db()
        first = crud.get_user_by_email("legacy@example.com")
        models.init_db()
        second = crud.get_user_by_email("legacy@example.com")

        self.assertEqual(str(uuid.UUID(first["public_id"])), first["public_id"])
        self.assertEqual(first["public_id"], second["public_id"])
        self.assertEqual(first["token_version"], 0)


class StampedMigrationUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "stamped.db")
        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": f"sqlite+pysqlite:///{self.database_path}",
                "K_SERVICE": "",
            },
            clear=False,
        )
        self.env_patch.start()
        models.reset_engine()

    def tearDown(self):
        models.reset_engine()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_database_already_stamped_at_0001_receives_0002(self):
        engine = models.get_engine()
        with engine.begin() as connection:
            command.upgrade(
                models._alembic_config(connection),
                "20260729_0001",
            )
            self.assertNotIn(
                "managed_admin_state",
                inspect(connection).get_table_names(),
            )

        models.init_db()

        with engine.connect() as connection:
            self.assertIn(
                "managed_admin_state",
                inspect(connection).get_table_names(),
            )
