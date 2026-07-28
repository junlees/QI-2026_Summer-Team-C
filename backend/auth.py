"""JWT auth: password hashing, token issue/verify, and route decorators.

Deliberately DB-free — app.py owns the user lookups; this module only turns a
user row into a token and a token back into g.user. Keeps the layering clean
(ai/ never sees auth, auth never sees the DB).
"""
import functools
import logging
import os
from datetime import datetime, timedelta, timezone

import jwt
from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

JWT_TTL = timedelta(days=7)
_DEV_SECRET = "dev-insecure-secret"
_warned_dev_secret = False

logger = logging.getLogger(__name__)


def _secret():
    global _warned_dev_secret
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    if not _warned_dev_secret:
        logger.warning(
            "JWT_SECRET is not set — using an insecure dev fallback. "
            "Set JWT_SECRET before deploying."
        )
        _warned_dev_secret = True
    return _DEV_SECRET


def hash_password(password):
    # pbkdf2, not werkzeug's scrypt default: scrypt allocates ~32MB per call,
    # which is unwelcome on a 2Gi Cloud Run instance that already holds torch
    # and serves 4 gunicorn threads.
    return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def issue_token(user):
    payload = {
        "uid": user["id"],
        "email": user["email"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + JWT_TTL,
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token):
    """Payload dict, or None for an expired/invalid/garbage token."""
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError:  # includes ExpiredSignatureError
        return None


def _unauthorized():
    return jsonify({
        "status": "error",
        "message": "Authentication required. Please log in.",
    }), 401


def require_auth(fn):
    """Reads `Authorization: Bearer <token>` and sets g.user = {uid, email, role}."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return _unauthorized()
        payload = decode_token(header[len("Bearer "):].strip())
        if payload is None:
            return _unauthorized()
        g.user = {"uid": payload["uid"], "email": payload["email"], "role": payload["role"]}
        return fn(*args, **kwargs)
    return wrapper


def require_admin(fn):
    @functools.wraps(fn)
    @require_auth
    def wrapper(*args, **kwargs):
        if g.user["role"] != "admin":
            return jsonify({"status": "error", "message": "Admin access required."}), 403
        return fn(*args, **kwargs)
    return wrapper
