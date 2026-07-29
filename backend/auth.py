"""JWT authentication with revocable, database-backed authorization."""

import functools
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash


JWT_TTL = timedelta(days=7)
JWT_ISSUER = "agrisage"
JWT_AUDIENCE = "agrisage-api"
MIN_JWT_SECRET_BYTES = 32
_INSECURE_EXAMPLE_SECRETS = {
    "dev-insecure-secret",
    "your-random-secret-here",
    "replace-with-at-least-32-random-bytes",
}


def _secret():
    secret = os.environ.get("JWT_SECRET")
    if (
        not secret
        or not secret.strip()
        or len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES
        or secret.strip() in _INSECURE_EXAMPLE_SECRETS
    ):
        raise RuntimeError(
            "JWT_SECRET must be a non-example random value containing at least "
            "32 UTF-8 bytes."
        )
    return secret


def validate_config():
    """Fail application startup when the signing configuration is unsafe."""
    _secret()


def hash_password(password):
    return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def issue_token(user):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["public_id"]),
        "token_version": int(user["token_version"]),
        "iat": now,
        "exp": now + JWT_TTL,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token):
    """Return a validated payload, or None for expired/malformed credentials."""
    try:
        payload = jwt.decode(
            token,
            _secret(),
            algorithms=["HS256"],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={
                "require": [
                    "sub",
                    "token_version",
                    "iat",
                    "exp",
                    "iss",
                    "aud",
                    "jti",
                ]
            },
        )
        subject = payload["sub"]
        token_version = payload["token_version"]
        if not isinstance(subject, str) or str(uuid.UUID(subject)) != subject:
            return None
        if type(token_version) is not int or token_version < 0:
            return None
        return payload
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def _unauthorized():
    return jsonify(
        {
            "status": "error",
            "message": "Authentication required. Please log in.",
        }
    ), 401


def require_auth(fn):
    """Resolve every bearer token to the current database user and permissions."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return _unauthorized()

        payload = decode_token(header[len("Bearer ") :].strip())
        if payload is None:
            return _unauthorized()

        loader = current_app.config.get("AUTH_USER_LOADER")
        if not callable(loader):
            raise RuntimeError("AUTH_USER_LOADER is not configured")

        user = loader(payload["sub"])
        if user is None or int(user["token_version"]) != payload["token_version"]:
            return _unauthorized()

        # Authorization data is always current DB state, never a JWT role claim.
        g.current_user = user
        g.user = {
            "uid": user["id"],
            "public_id": user["public_id"],
            "email": user["email"],
            "role": user["role"],
        }
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn):
    @functools.wraps(fn)
    @require_auth
    def wrapper(*args, **kwargs):
        if g.user["role"] != "admin":
            return jsonify(
                {"status": "error", "message": "Admin access required."}
            ), 403
        return fn(*args, **kwargs)

    return wrapper
