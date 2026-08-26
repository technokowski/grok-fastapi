from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile

from app.config import (
    FFMPEG_BIN,
    FFMPEG_TIMEOUT_SECS,
    MAX_UPLOAD_BYTES,
    SHARE_DIR,
    UPLOADS_DIR,
)
from app.security import new_token

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_uploads_dir() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_share_dir() -> None:
    SHARE_DIR.mkdir(parents=True, exist_ok=True)


def user_dir(username: str) -> Path:
    ensure_uploads_dir()
    folder = (UPLOADS_DIR / username).resolve()
    if folder.parent != UPLOADS_DIR.resolve():
        raise ValueError("Invalid upload directory.")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def safe_filename(name: str | None) -> str | None:
    if not name:
        return None
    name = Path(name).name
    name = name.strip().replace("\x00", "")
    name = SAFE_NAME_RE.sub("_", name)
    name = name.strip("._")
    if not name or name in {".", ".."}:
        return None
    return name[:180]


def unique_path(folder: Path, name: str) -> Path:
    path = folder / name
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        candidate = folder / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def resolve_user_file(username: str, filename: str) -> Path | None:
    folder = user_dir(username)
    name = safe_filename(filename)
    if not name:
        return None
    path = (folder / name).resolve()
    try:
        path.relative_to(folder)
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def delete_user_file(username: str, filename: str) -> str:
    path = resolve_user_file(username, filename)
    if path is None:
        raise ValueError("File not found.")
    name = path.name
    path.unlink()
    return name


def list_user_files(username: str) -> list[dict]:
    folder = user_dir(username)
    rows = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        stat = path.stat()
        rows.append(
            {
                "name": path.name,
                "size": _format_size(stat.st_size),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return rows


def save_upload(username: str, upload: UploadFile) -> Path:
    name = safe_filename(upload.filename)
    if not name:
        raise ValueError("That filename is not allowed.")
    dest = unique_path(user_dir(username), name)
    size = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValueError("File is larger than the 50 MB limit.")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise ValueError("The file was empty.")
    return dest


def is_wav(path: Path) -> bool:
    return path.suffix.lower() == ".wav"


def convert_wav_to_mp3(wav_path: Path) -> Path:
    ffmpeg = shutil.which(FFMPEG_BIN)
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed on this machine.")
    mp3_path = wav_path.with_suffix(".mp3")
    result = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(mp3_path),
        ],
        capture_output=True,
        timeout=FFMPEG_TIMEOUT_SECS,
        check=False,
    )
    if result.returncode != 0 or not mp3_path.is_file():
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or "ffmpeg could not convert that file.")
    return mp3_path


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def copy_to_share(src: Path, original_name: str) -> str:
    ensure_share_dir()
    safe = safe_filename(original_name) or "file"
    stored_name = f"{new_token(8)}_{safe}"
    dest = (SHARE_DIR / stored_name).resolve()
    try:
        dest.relative_to(SHARE_DIR.resolve())
    except ValueError as exc:
        raise ValueError("Invalid share path.") from exc
    shutil.copy2(src, dest)
    return stored_name


def resolve_share_file(stored_name: str) -> Path | None:
    if not stored_name or stored_name != Path(stored_name).name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]+", stored_name):
        return None
    ensure_share_dir()
    path = (SHARE_DIR / stored_name).resolve()
    try:
        path.relative_to(SHARE_DIR.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def remove_share_file(stored_name: str) -> None:
    path = resolve_share_file(stored_name)
    if path is not None:
        path.unlink(missing_ok=True)
