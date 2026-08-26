from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
UPLOADS_DIR = DATA_DIR / "uploads"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
FFMPEG_BIN = "ffmpeg"
FFMPEG_TIMEOUT_SECS = 300

SESSION_COOKIE = "sid"
CSRF_COOKIE = "csrf_token"
FLASH_COOKIE = "flash"

SESSION_TTL_DAYS = 7
RESET_TTL_HOURS = 1
MIN_PASSWORD_LENGTH = 12
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_MINUTES = 15

PUBLIC_PATHS = {
    "/login",
    "/forgot-password",
}
PUBLIC_PREFIXES = (
    "/static/",
    "/reset-password/",
)

BOOTSTRAP_USERNAME = "admin"
BOOTSTRAP_PASSWORD = "root"
