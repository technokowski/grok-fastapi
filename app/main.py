from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.auth import (
    authenticate,
    client_ip,
    create_reset_token,
    create_session,
    destroy_session,
    destroy_user_sessions,
    get_reset_user,
    load_user_for_request,
    record_login_attempt,
    too_many_attempts,
)
from app.config import APP_DIR, PUBLIC_PATHS, PUBLIC_PREFIXES
from app.db import get_db, init_db
from app.files import (
    convert_wav_to_mp3,
    delete_user_file,
    is_wav,
    list_user_files,
    resolve_user_file,
    save_upload,
)
from app.models import User
from app.security import (
    hash_password,
    normalize_username,
    utcnow,
    validate_password,
    validate_username,
    verify_password,
)
from app.web import (
    check_csrf,
    clear_session_cookie,
    redirect,
    render,
    set_session_cookie,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Grok FastAPI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static/"):
        return await call_next(request)

    db = next(get_db())
    try:
        request.state.user = load_user_for_request(db, request)
    finally:
        db.close()

    user = request.state.user

    if _is_public(path):
        if user and path == "/login":
            return redirect("/")
        return await call_next(request)

    if user is None:
        return redirect("/login")

    allowed_while_must_change = {"/change-password", "/logout"}
    if user.must_change_password and path not in allowed_while_must_change:
        return redirect(
            "/change-password",
            "You must change your password before continuing.",
            "error",
        )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Pages
# To add a page:
#   1. Copy a GET route below and point it at a new template.
#   2. Add {"path": "/your-page", "title": "Your Page"} to NAV_ITEMS in app/web.py
#      (use "admin_only": True if only admins should see it in the nav).
# Auth is applied automatically; you do not register extra routers.
# ---------------------------------------------------------------------------


@app.get("/")
def home(request: Request):
    return render(request, "welcome.html")


@app.get("/hello")
def hello(request: Request):
    return render(request, "hello.html")

@app.get("/elite")
def elite(request: Request):
    return render(request, "elite.html")


@app.get("/files")
def files_page(request: Request):
    return render(
        request,
        "files.html",
        files=list_user_files(request.state.user.username),
    )


@app.post("/files/upload")
def files_upload(
    request: Request,
    file: UploadFile = File(...),
    csrf: str = Form(""),
):
    if not check_csrf(request, csrf):
        return redirect("/files", "Invalid form token.", "error")
    try:
        saved = save_upload(request.state.user.username, file)
    except ValueError as exc:
        return redirect("/files", str(exc), "error")
    if is_wav(saved):
        try:
            mp3 = convert_wav_to_mp3(saved)
        except Exception as exc:
            detail = str(exc).strip().replace("\n", " ")
            if len(detail) > 80:
                detail = detail[:77] + "..."
            return redirect(
                "/files",
                f"Saved {saved.name}, but conversion failed: {detail}",
                "error",
            )
        return redirect("/files", f"Saved {saved.name} and converted to {mp3.name}.")
    return redirect("/files", f"Saved {saved.name}.")


@app.get("/files/download/{filename}")
def files_download(request: Request, filename: str):
    path = resolve_user_file(request.state.user.username, filename)
    if path is None:
        return redirect("/files", "File not found.", "error")
    return FileResponse(path, filename=path.name)


@app.post("/files/delete")
def files_delete(
    request: Request,
    filename: str = Form(...),
    csrf: str = Form(""),
):
    if not check_csrf(request, csrf):
        return redirect("/files", "Invalid form token.", "error")
    try:
        name = delete_user_file(request.state.user.username, filename)
    except ValueError as exc:
        return redirect("/files", str(exc), "error")
    return redirect("/files", f"Deleted {name}.")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@app.get("/login")
def login_form(request: Request):
    return render(request, "login.html")


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not check_csrf(request, csrf):
        return render(request, "login.html", error="Invalid form token. Try again.", status_code=403)

    username = normalize_username(username)
    ip = client_ip(request)

    if too_many_attempts(db, username, ip):
        return render(
            request,
            "login.html",
            error="Too many sign-in attempts. Try again in 15 minutes.",
            status_code=429,
        )

    user = authenticate(db, username, password)
    if user is None:
        record_login_attempt(db, username, ip, False)
        return render(request, "login.html", error="Invalid username or password.", status_code=401)

    record_login_attempt(db, username, ip, True)
    sid = create_session(db, user)
    target = "/change-password" if user.must_change_password else "/"
    message = "Choose a new password before using the site." if user.must_change_password else None
    response = redirect(target, message, "error" if message else "ok")
    set_session_cookie(response, sid)
    return response


@app.post("/logout")
def logout(
    request: Request,
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not check_csrf(request, csrf):
        return redirect("/", "Invalid form token.", "error")
    user = getattr(request.state, "user", None)
    if user:
        destroy_session(db, user.session_id)
    response = redirect("/login", "Signed out.")
    clear_session_cookie(response)
    return response


@app.get("/change-password")
def change_password_form(request: Request):
    user = request.state.user
    return render(request, "change_password.html", force=user.must_change_password)


@app.post("/change-password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    user = request.state.user
    if not check_csrf(request, csrf):
        return render(
            request,
            "change_password.html",
            force=user.must_change_password,
            error="Invalid form token. Try again.",
            status_code=403,
        )

    row = db.get(User, user.id)
    if row is None:
        return redirect("/login", "Session expired.", "error")

    if not verify_password(current_password, row.password_hash):
        return render(
            request,
            "change_password.html",
            force=row.must_change_password,
            error="Current password is incorrect.",
            status_code=400,
        )
    if new_password != confirm_password:
        return render(
            request,
            "change_password.html",
            force=row.must_change_password,
            error="New passwords do not match.",
            status_code=400,
        )
    problem = validate_password(new_password, row.username)
    if problem:
        return render(
            request,
            "change_password.html",
            force=row.must_change_password,
            error=problem,
            status_code=400,
        )
    if verify_password(new_password, row.password_hash):
        return render(
            request,
            "change_password.html",
            force=row.must_change_password,
            error="New password must be different from the current password.",
            status_code=400,
        )

    row.password_hash = hash_password(new_password)
    row.must_change_password = False
    row.password_changed_at = utcnow()
    db.commit()
    destroy_user_sessions(db, row.id, keep_session_id=user.session_id)
    return redirect("/", "Password updated.")


@app.get("/forgot-password")
def forgot_password_form(request: Request):
    return render(request, "forgot_password.html")


@app.post("/forgot-password")
def forgot_password(
    request: Request,
    username: str = Form(...),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not check_csrf(request, csrf):
        return render(request, "forgot_password.html", error="Invalid form token. Try again.", status_code=403)

    username = normalize_username(username)
    row = db.scalar(select(User).where(User.username == username))
    if row is not None and row.is_active:
        row.reset_requested = True
        db.commit()
    return render(
        request,
        "forgot_password.html",
        info="If that account exists, an administrator can issue a reset link from the Users page.",
    )


@app.get("/reset-password/{token}")
def reset_password_form(request: Request, token: str, db: Session = Depends(get_db)):
    found = get_reset_user(db, token)
    if found is None:
        return render(request, "reset_password.html", invalid=True, token=token)
    return render(request, "reset_password.html", invalid=False, token=token)


@app.post("/reset-password/{token}")
def reset_password(
    request: Request,
    token: str,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not check_csrf(request, csrf):
        return render(
            request,
            "reset_password.html",
            invalid=False,
            token=token,
            error="Invalid form token. Try again.",
            status_code=403,
        )

    found = get_reset_user(db, token)
    if found is None:
        return render(request, "reset_password.html", invalid=True, token=token)

    reset_row, user = found
    if new_password != confirm_password:
        return render(
            request,
            "reset_password.html",
            invalid=False,
            token=token,
            error="Passwords do not match.",
            status_code=400,
        )
    problem = validate_password(new_password, user.username)
    if problem:
        return render(
            request,
            "reset_password.html",
            invalid=False,
            token=token,
            error=problem,
            status_code=400,
        )

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    user.reset_requested = False
    reset_row.used_at = utcnow()
    db.commit()
    destroy_user_sessions(db, user.id)
    return redirect("/login", "Password reset. Sign in with your new password.")


# ---------------------------------------------------------------------------
# Users (admin)
# ---------------------------------------------------------------------------


@app.get("/users")
def users_list(request: Request, db: Session = Depends(get_db)):
    if not request.state.user.is_admin:
        return redirect("/", "Admins only.", "error")
    users = db.scalars(select(User).order_by(User.username)).all()
    return render(request, "users.html", users=users)


@app.get("/users/new")
def user_create_form(request: Request):
    if not request.state.user.is_admin:
        return redirect("/", "Admins only.", "error")
    return render(request, "user_create.html")


@app.post("/users/new")
def user_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    is_admin: str | None = Form(None),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not request.state.user.is_admin:
        return redirect("/", "Admins only.", "error")
    if not check_csrf(request, csrf):
        return render(request, "user_create.html", error="Invalid form token. Try again.", status_code=403)

    username = normalize_username(username)
    problem = validate_username(username)
    if problem:
        return render(request, "user_create.html", error=problem, username=username, status_code=400)
    if password != confirm_password:
        return render(
            request,
            "user_create.html",
            error="Passwords do not match.",
            username=username,
            status_code=400,
        )
    problem = validate_password(password, username)
    if problem:
        return render(request, "user_create.html", error=problem, username=username, status_code=400)
    existing = db.scalar(select(User).where(User.username == username))
    if existing:
        return render(
            request,
            "user_create.html",
            error="That username is already taken.",
            username=username,
            status_code=400,
        )

    db.add(
        User(
            username=username,
            password_hash=hash_password(password),
            is_admin=is_admin == "on",
            is_active=True,
            must_change_password=True,
        )
    )
    db.commit()
    return redirect("/users", f"Created user {username}. They must change their password on first sign-in.")


@app.post("/users/{user_id}/reset-link")
def user_reset_link(
    request: Request,
    user_id: int,
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not request.state.user.is_admin:
        return redirect("/", "Admins only.", "error")
    if not check_csrf(request, csrf):
        return redirect("/users", "Invalid form token.", "error")

    row = db.get(User, user_id)
    if row is None or not row.is_active:
        return redirect("/users", "User not found.", "error")

    token = create_reset_token(db, row)
    reset_url = str(request.base_url).rstrip("/") + f"/reset-password/{token}"
    return render(request, "reset_link.html", target_user=row, reset_url=reset_url)
