"""PostgreSQL integration coverage for production-only P0 behavior.

Set TEST_POSTGRES_DATABASE_URL to a dedicated, empty database whose name ends
in ``_test``. The suite is skipped otherwise; CI supplies an ephemeral server.
"""

import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from alembic import command
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.engine import make_url


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db import crud, models  # noqa: E402


TEST_DATABASE_URL = (os.environ.get("TEST_POSTGRES_DATABASE_URL") or "").strip()


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "TEST_POSTGRES_DATABASE_URL is not configured",
)
class PostgresP0IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parsed = make_url(TEST_DATABASE_URL)
        if parsed.get_backend_name() != "postgresql" or not (
            parsed.database or ""
        ).endswith("_test"):
            raise RuntimeError(
                "TEST_POSTGRES_DATABASE_URL must target a PostgreSQL database "
                "whose name ends in '_test'."
            )

        cls.env_patch = mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": TEST_DATABASE_URL,
                "K_SERVICE": "agrisage-integration-test",
            },
            clear=False,
        )
        cls.env_patch.start()
        models.reset_engine()
        cls.engine = models.get_engine()

        with cls.engine.connect() as connection:
            existing = set(inspect(connection).get_table_names())
        if existing:
            raise RuntimeError(
                "PostgreSQL integration tests require an empty dedicated database; "
                f"found: {', '.join(sorted(existing))}"
            )

        # Exercise the real stamped-database path, not only upgrade-to-head.
        with cls.engine.begin() as connection:
            command.upgrade(
                models._alembic_config(connection),
                "20260729_0001",
            )
            if "managed_admin_state" in inspect(connection).get_table_names():
                raise AssertionError("0001 unexpectedly contains 0002 schema")

        models.init_db()

    @classmethod
    def tearDownClass(cls):
        models.reset_engine()
        cls.env_patch.stop()

    def _create_user(self, email):
        return crud.create_user(
            email,
            "test-password-hash",
            "conventional",
            "self_consumption",
        )

    def test_01_migration_and_schema_validation_are_restart_safe(self):
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    select(models.managed_admin_state.c.config_version)
                ).first(),
                None,
            )
            models._validate_postgres_schema(connection)

        models.reset_engine()
        models.init_db()
        self.engine = models.get_engine()

    def test_02_concurrent_admin_versions_converge_to_highest(self):
        crud.apply_managed_admin_config(
            "initial-admin@example.com",
            "initial-hash",
            1,
        )
        barrier = threading.Barrier(2)

        def apply(email, password_hash, version):
            barrier.wait()
            return crud.apply_managed_admin_config(email, password_hash, version)

        with ThreadPoolExecutor(max_workers=2) as executor:
            lower = executor.submit(
                apply,
                "lower-admin@example.com",
                "lower-hash",
                2,
            )
            higher = executor.submit(
                apply,
                "higher-admin@example.com",
                "higher-hash",
                3,
            )
            lower.result(timeout=15)
            higher.result(timeout=15)

        current = crud.get_user_by_email("higher-admin@example.com")
        self.assertEqual(current["role"], "admin")
        self.assertEqual(current["password_hash"], "higher-hash")
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    select(models.managed_admin_state.c.config_version)
                ).scalar_one(),
                3,
            )
            self.assertEqual(
                connection.execute(
                    select(func.count())
                    .select_from(models.users)
                    .where(models.users.c.role == "admin")
                ).scalar_one(),
                1,
            )

    def test_03_signup_email_conflict_never_returns_admin_snapshot(self):
        for version in range(10, 13):
            email = f"signup-race-{version}@example.com"
            barrier = threading.Barrier(2)

            def signup():
                barrier.wait()
                try:
                    return self._create_user(email)
                except crud.DuplicateEmailError:
                    return None

            def promote():
                barrier.wait()
                return crud.apply_managed_admin_config(
                    email,
                    f"admin-hash-{version}",
                    version,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                signup_future = executor.submit(signup)
                promote_future = executor.submit(promote)
                signup_snapshot = signup_future.result(timeout=15)
                promote_future.result(timeout=15)

            current = crud.get_user_by_email(email)
            self.assertEqual(current["role"], "admin")
            if signup_snapshot is not None:
                self.assertEqual(signup_snapshot["role"], "user")
                self.assertLess(
                    signup_snapshot["token_version"],
                    current["token_version"],
                )

    def test_04_postgres_foreign_key_actions_match_application_contract(self):
        user = self._create_user("postgres-fk@example.com")
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
            result={"class_id": "Apple___Apple_scab"},
            follow_up_target_date="2026-08-01",
            user_id=user["id"],
        )

        self.assertTrue(crud.delete_crop(user["id"], crop["id"]))
        self.assertIsNone(crud.get_diagnosis(user["id"], diagnosis_id)["crop_id"])

        with self.engine.begin() as connection:
            connection.execute(
                delete(models.users).where(models.users.c.id == user["id"])
            )
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    select(func.count())
                    .select_from(models.diagnoses)
                    .where(models.diagnoses.c.id == diagnosis_id)
                ).scalar_one(),
                0,
            )
            self.assertEqual(
                connection.execute(
                    select(func.count()).select_from(models.follow_up_reminders)
                ).scalar_one(),
                0,
            )
