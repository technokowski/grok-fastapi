from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import (
    LOGIN_MAX_FAILURES,
    LOGIN_WINDOW_MINUTES,
    RESET_TTL_HOURS,
    SESSION_COOKIE,
    SESSION_TTL_DAYS,
)
from app.models import AuthSession, LoginAttempt, PasswordReset, User
from app.security import (
    digest_equal,
    hash_token,
    new_token,
    reset_expiry,
    session_expiry,
    utcnow,
    verify_password,
    verify_password_dummy,
)


@dataclass
class CurrentUser:
    id: int
    username: str
    is_admin: bool
    must_change_password: bool
    session_id: str


def client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


def load_user_for_request(db: Session, request: Request) -> CurrentUser | None:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    row = db.get(AuthSession, sid)
    if row is None or row.expires_at < utcnow():
        if row is not None:
            db.delete(row)
            db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        db.delete(row)
        db.commit()
        return None
    row.last_seen_at = utcnow()
    db.commit()
    return CurrentUser(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
        session_id=row.id,
    )


def too_many_attempts(db: Session, username: str, ip: str) -> bool:
    since = utcnow() - timedelta(minutes=LOGIN_WINDOW_MINUTES)
    count = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= since,
            LoginAttempt.username == username,
            LoginAttempt.ip == ip,
        )
    )
    return (count or 0) >= LOGIN_MAX_FAILURES


def record_login_attempt(db: Session, username: str, ip: str, success: bool) -> None:
    db.add(LoginAttempt(username=username, ip=ip, success=success, attempted_at=utcnow()))
    db.commit()


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_password_dummy(password)
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def create_session(db: Session, user: User) -> str:
    sid = new_token(32)
    db.add(
        AuthSession(
            id=sid,
            user_id=user.id,
            expires_at=session_expiry(SESSION_TTL_DAYS),
            last_seen_at=utcnow(),
        )
    )
    db.commit()
    return sid


def destroy_session(db: Session, session_id: str | None) -> None:
    if not session_id:
        return
    row = db.get(AuthSession, session_id)
    if row is not None:
        db.delete(row)
        db.commit()


def destroy_user_sessions(db: Session, user_id: int, keep_session_id: str | None = None) -> None:
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep_session_id:
        stmt = stmt.where(AuthSession.id != keep_session_id)
    db.execute(stmt)
    db.commit()


def create_reset_token(db: Session, user: User) -> str:
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    token = new_token(32)
    db.add(
        PasswordReset(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=reset_expiry(RESET_TTL_HOURS),
        )
    )
    user.reset_requested = False
    db.commit()
    return token


def get_reset_user(db: Session, token: str) -> tuple[PasswordReset, User] | None:
    token_hash = hash_token(token)
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_hash))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        digest_equal(token_hash, token_hash)
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return row, user
