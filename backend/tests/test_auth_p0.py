import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

import jwt
from flask import Flask, g, jsonify


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth  # noqa: E402


TEST_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"


class JwtConfigurationTests(unittest.TestCase):
    def test_secret_is_required_and_must_be_at_least_32_bytes(self):
        for value in (
            None,
            "",
            "x" * 31,
            "replace-with-at-least-32-random-bytes",
            " replace-with-at-least-32-random-bytes ",
        ):
            with self.subTest(value=value):
                with mock.patch.dict(os.environ, {}, clear=False):
                    if value is None:
                        os.environ.pop("JWT_SECRET", None)
                    else:
                        os.environ["JWT_SECRET"] = value
                    with self.assertRaisesRegex(RuntimeError, "at least 32"):
                        auth.validate_config()

    def test_token_uses_uuid_subject_and_version_not_authoritative_role(self):
        user = {
            "public_id": str(uuid.uuid4()),
            "token_version": 3,
            "id": 42,
            "email": "user@example.com",
            "role": "admin",
        }
        with mock.patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET}, clear=False):
            encoded = auth.issue_token(user)
            payload = auth.decode_token(encoded)

        self.assertEqual(payload["sub"], user["public_id"])
        self.assertEqual(payload["token_version"], 3)
        self.assertNotIn("uid", payload)
        self.assertNotIn("email", payload)
        self.assertNotIn("role", payload)


class DatabaseBackedAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.secret_patch = mock.patch.dict(
            os.environ,
            {"JWT_SECRET": TEST_SECRET},
            clear=False,
        )
        self.secret_patch.start()
        self.user = {
            "id": 7,
            "public_id": str(uuid.uuid4()),
            "token_version": 0,
            "email": "user@example.com",
            "role": "user",
            "certification": "conventional",
            "purpose": "self_consumption",
            "daily_limit": 3,
        }
        self.app = Flask(__name__)
        self.app.config["AUTH_USER_LOADER"] = self._load_user

        @self.app.get("/protected")
        @auth.require_auth
        def protected():
            return jsonify(
                {
                    "uid": g.user["uid"],
                    "public_id": g.user["public_id"],
                    "role": g.user["role"],
                }
            )

        @self.app.get("/admin")
        @auth.require_admin
        def admin_only():
            return jsonify({"status": "ok"})

        self.client = self.app.test_client()

    def tearDown(self):
        self.secret_patch.stop()

    def _load_user(self, public_id):
        if public_id != self.user["public_id"]:
            return None
        return dict(self.user)

    def _authorization(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_stale_token_version_is_rejected(self):
        token = auth.issue_token(self.user)
        self.user["token_version"] = 1

        response = self.client.get("/protected", headers=self._authorization(token))

        self.assertEqual(response.status_code, 401)

    def test_deleted_or_recreated_integer_id_cannot_reuse_old_token(self):
        token = auth.issue_token(self.user)
        self.user["public_id"] = str(uuid.uuid4())

        response = self.client.get("/protected", headers=self._authorization(token))

        self.assertEqual(response.status_code, 401)

    def test_forged_role_claim_does_not_override_database_role(self):
        payload = auth.decode_token(auth.issue_token(self.user))
        payload["role"] = "admin"
        forged = jwt.encode(payload, TEST_SECRET, algorithm="HS256")

        response = self.client.get("/admin", headers=self._authorization(forged))

        self.assertEqual(response.status_code, 403)

    def test_current_database_role_is_applied_immediately(self):
        token = auth.issue_token(self.user)
        self.user["role"] = "admin"

        response = self.client.get("/admin", headers=self._authorization(token))

        self.assertEqual(response.status_code, 200)

    def test_missing_required_claim_returns_401_not_500(self):
        malformed = jwt.encode(
            {
                "iat": 1,
                "exp": 4_102_444_800,
                "iss": auth.JWT_ISSUER,
                "aud": auth.JWT_AUDIENCE,
            },
            TEST_SECRET,
            algorithm="HS256",
        )

        response = self.client.get(
            "/protected",
            headers=self._authorization(malformed),
        )

        self.assertEqual(response.status_code, 401)
