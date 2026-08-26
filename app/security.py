from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

import bcrypt

from app.config import MIN_PASSWORD_LENGTH

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")

COMMON_PASSWORDS = frozenset(
    {
        "root",
        "password",
        "password123",
        "admin",
        "admin123",
        "changeme",
        "letmein",
        "qwerty",
        "12345678",
        "123456789012",
    }
)

# Dummy hash so a missing user still pays bcrypt cost (less username enumeration).
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-not-used", bcrypt.gensalt(rounds=12))


def utcnow() -> datetime:
    return datetime.utcnow()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def verify_password_dummy(password: str) -> None:
    bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def digest_equal(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


def normalize_username(raw: str) -> str:
    return raw.strip().lower()


def validate_username(username: str) -> str | None:
    if not USERNAME_RE.match(username):
        return "Username must be 3–32 characters, start with a letter, and use only lowercase letters, numbers, or underscores."
    return None


def validate_password(password: str, username: str = "") -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if username and password.lower() == username.lower():
        return "Password cannot be the same as the username."
    if password.lower() in COMMON_PASSWORDS:
        return "That password is too common."
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        return "Password must include at least one letter and one number."
    return None


def session_expiry(days: int) -> datetime:
    return utcnow() + timedelta(days=days)


def reset_expiry(hours: int) -> datetime:
    return utcnow() + timedelta(hours=hours)
