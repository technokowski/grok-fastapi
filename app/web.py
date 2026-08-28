from __future__ import annotations

from urllib.parse import quote, unquote

from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.responses import Response

from app.auth import CurrentUser
from app.config import (
    APP_DIR,
    CSRF_COOKIE,
    FLASH_COOKIE,
    PUBLIC_SHARE_ENABLED,
    SESSION_COOKIE,
    SESSION_TTL_DAYS,
)
from app.db import SessionLocal
from app.files import list_public_shares
from app.security import digest_equal, new_token

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

NAV_ITEMS = [
    {"path": "/", "title": "Home"},
    {"path": "/hello", "title": "First Page"},
    {"path": "/files", "title": "Files"},
    {"path": "/users", "title": "Users", "admin_only": True},
    {"path": "/elite", "title": "1337"},
]


def visible_nav(user: CurrentUser | None) -> list[dict]:
    if user is None:
        return []
    items = []
    for item in NAV_ITEMS:
        if item.get("admin_only") and not user.is_admin:
            continue
        items.append(item)
    return items


def csrf_from(request: Request) -> str:
    return request.cookies.get(CSRF_COOKIE) or new_token(32)


def attach_csrf_cookie(response: Response, token: str, request: Request) -> None:
    if request.cookies.get(CSRF_COOKIE) == token:
        return
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        path="/",
    )


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def set_flash(response: Response, message: str, kind: str = "ok") -> None:
    value = f"{kind}:{message}"
    response.set_cookie(
        FLASH_COOKIE,
        quote(value, safe=": "),
        httponly=True,
        samesite="lax",
        path="/",
        max_age=120,
    )


def pop_flash(request: Request) -> dict | None:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    raw = unquote(raw)
    if ":" not in raw:
        return None
    kind, message = raw.split(":", 1)
    if kind not in {"ok", "error"}:
        return None
    if len(message) > 200:
        return None
    return {"kind": kind, "message": message}


def render(request: Request, template: str, status_code: int = 200, **ctx) -> Response:
    user: CurrentUser | None = getattr(request.state, "user", None)
    csrf_token = csrf_from(request)
    flash = pop_flash(request)
    if ctx.get("shared_files") is None and PUBLIC_SHARE_ENABLED:
        with SessionLocal() as db:
            ctx["shared_files"] = list_public_shares(db)
    elif ctx.get("shared_files") is None:
        ctx["shared_files"] = []
    response = templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "nav_items": visible_nav(user),
            "csrf_token": csrf_token,
            "flash": flash,
            "public_share_enabled": PUBLIC_SHARE_ENABLED,
            **ctx,
        },
        status_code=status_code,
    )
    attach_csrf_cookie(response, csrf_token, request)
    if flash is not None:
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response


def redirect(url: str, flash: str | None = None, kind: str = "ok") -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    if flash:
        set_flash(response, flash, kind)
    return response


def check_csrf(request: Request, token: str | None) -> bool:
    return digest_equal(request.cookies.get(CSRF_COOKIE), token)
