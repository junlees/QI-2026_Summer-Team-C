import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# app.py runs migrations at import time. Point initialization at an isolated
# temporary SQLite database so this test never touches local runtime data.
_DB_DIR = tempfile.TemporaryDirectory()
from db import models as db_models  # noqa: E402

_ORIGINAL_DB_PATH = db_models.DB_PATH
db_models.DB_PATH = os.path.join(_DB_DIR.name, "test.db")

_ENV_PATCH = mock.patch.dict(
    os.environ,
    {
        "ADMIN_ID": "",
        "ADMIN_PASSWORD": "",
        "ADMIN_CONFIG_VERSION": "",
        "DATABASE_URL": f"sqlite+pysqlite:///{os.path.join(_DB_DIR.name, 'test.db')}",
        "K_SERVICE": "",
        "OPENAI_API_KEY": "",
        "JWT_SECRET": "test-only-jwt-secret-that-is-at-least-32-bytes",
    },
    clear=False,
)
_ENV_PATCH.start()
import app as app_module  # noqa: E402

from ai import pipeline  # noqa: E402
from flask import g  # noqa: E402


def tearDownModule():
    db_models.reset_engine()
    db_models.DB_PATH = _ORIGINAL_DB_PATH
    _ENV_PATCH.stop()
    _DB_DIR.cleanup()


class ModelUnavailableTests(unittest.TestCase):
    def test_missing_checkpoint_raises_model_unavailable(self):
        missing_path = os.path.join(_DB_DIR.name, "missing-model.pth")

        with (
            mock.patch.dict(
                os.environ,
                {"MODEL_CHECKPOINT_PATH": missing_path},
                clear=False,
            ),
            mock.patch.dict(
                pipeline._model_state,
                {"model": None, "classes": None, "device": None},
                clear=True,
            ),
        ):
            with self.assertRaisesRegex(
                pipeline.ModelUnavailableError,
                "Model checkpoint not found",
            ):
                pipeline._load_classifier()

    def test_diagnose_returns_503_when_model_is_unavailable(self):
        crop = {
            "id": 7,
            "purpose_override": None,
            "growing_environment": "open_field",
            "harvest_date": None,
        }
        user = {
            "id": 1,
            "purpose": "self_consumption",
            "certification": "conventional",
            "daily_limit": None,
        }

        with tempfile.TemporaryDirectory() as upload_dir:
            with app_module.app.test_request_context(
                "/api/diagnose",
                method="POST",
                data={
                    "crop_id": "7",
                    "image": (io.BytesIO(b"not-an-image"), "leaf.jpg"),
                },
                content_type="multipart/form-data",
            ):
                g.user = {"uid": 1, "email": "user@example.com", "role": "user"}

                with (
                    mock.patch.object(app_module, "UPLOAD_DIR", upload_dir),
                    mock.patch.object(app_module.crud, "get_crop", return_value=crop),
                    mock.patch.object(
                        app_module,
                        "_current_user_or_401",
                        return_value=user,
                    ),
                    mock.patch.object(
                        app_module.pipeline,
                        "diagnose",
                        side_effect=pipeline.ModelUnavailableError(
                            "Model checkpoint not found: internal-path"
                        ),
                    ),
                    mock.patch.object(app_module.crud, "save_diagnosis") as save,
                ):
                    response, status = app_module.diagnose.__wrapped__()

                self.assertEqual(status, 503)
                self.assertEqual(
                    response.get_json(),
                    {
                        "status": "error",
                        "code": "model_unavailable",
                        "message": (
                            "The diagnosis model is temporarily unavailable. "
                            "Please try again later."
                        ),
                    },
                )
                save.assert_not_called()
                self.assertEqual(os.listdir(upload_dir), [])


class ManagedAdminStartupTests(unittest.TestCase):
    def setUp(self):
        with db_models.get_engine().begin() as connection:
            connection.execute(db_models.managed_admin_state.delete())
            connection.execute(db_models.users.delete())

    def test_same_version_conflict_fails_and_stale_revision_cannot_revert(self):
        base = {
            "ADMIN_ID": "managed-admin@example.com",
            "ADMIN_CONFIG_VERSION": "100",
        }
        with mock.patch.dict(
            os.environ,
            {**base, "ADMIN_PASSWORD": "first-safe-password"},
            clear=False,
        ):
            app_module._seed_admin()

        with mock.patch.dict(
            os.environ,
            {**base, "ADMIN_PASSWORD": "conflicting-password"},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "Increment"):
                app_module._seed_admin()

        with mock.patch.dict(
            os.environ,
            {
                **base,
                "ADMIN_PASSWORD": "second-safe-password",
                "ADMIN_CONFIG_VERSION": "101",
            },
            clear=False,
        ):
            app_module._seed_admin()

        with mock.patch.dict(
            os.environ,
            {**base, "ADMIN_PASSWORD": "first-safe-password"},
            clear=False,
        ):
            app_module._seed_admin()

        user = app_module.crud.get_user_by_email(base["ADMIN_ID"])
        self.assertTrue(
            app_module.auth.verify_password(
                user["password_hash"],
                "second-safe-password",
            )
        )
        self.assertFalse(
            app_module.auth.verify_password(
                user["password_hash"],
                "first-safe-password",
            )
        )

    def test_signup_token_never_inherits_a_concurrent_admin_promotion(self):
        client = app_module.app.test_client()
        original_create_user = app_module.crud.create_user

        def create_then_promote(*args, **kwargs):
            signup_snapshot = original_create_user(*args, **kwargs)
            app_module.crud.apply_managed_admin_config(
                signup_snapshot["email"],
                app_module.auth.hash_password("managed-safe-password"),
                1,
            )
            return signup_snapshot

        with mock.patch.object(
            app_module.crud,
            "create_user",
            side_effect=create_then_promote,
        ):
            response = client.post(
                "/api/signup",
                json={
                    "email": "race-before-token@example.com",
                    "password": "signup-password",
                },
            )

        self.assertEqual(response.status_code, 201)
        token = response.get_json()["token"]
        protected = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(protected.status_code, 401)

        response = client.post(
            "/api/signup",
            json={
                "email": "race-after-token@example.com",
                "password": "signup-password",
            },
        )
        self.assertEqual(response.status_code, 201)
        token = response.get_json()["token"]
        app_module.crud.apply_managed_admin_config(
            "race-after-token@example.com",
            app_module.auth.hash_password("next-managed-password"),
            2,
        )
        protected = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(protected.status_code, 401)


if __name__ == "__main__":
    unittest.main()
