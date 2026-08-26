# grok-fastapi

A small FastAPI site with sign-in, user admin, and a Files page that stores uploads and converts `.wav` to MP3.

## What to copy to the other computer

Copy the project folder, **except**:

| Skip | Why |
|---|---|
| `venv/` | Tied to that machine’s CPU, OS, and Python path. Recreate it (see below). |
| `data/` | Local SQLite database and uploaded files. Omit it for a fresh install. Copy it only if you want to keep existing users and files. |
| `__pycache__/` | Regenerated automatically. |

`.gitignore` already excludes `venv/` and `data/`. If you use git:

```bash
cd ~/Code/grok-fastapi
git init   # if you have not already
git add .
git status   # confirm venv/ and data/ are not listed
```

Then clone on the other computer, or copy the folder and delete `venv` there.

Do **not** zip and move `venv`. It will often fail on another Mac (Apple Silicon vs Intel, different Python version, broken absolute paths). Recreating it takes about a minute.

## What macOS does not ship

The app needs these **system** pieces. None of them come with macOS by default:

| Dependency | Used for | Install on macOS |
|---|---|---|
| **Python 3.11+** | Running the app | [python.org](https://www.python.org/downloads/) or `brew install python` |
| **ffmpeg** with MP3 encoding (`libmp3lame`) | `.wav` → `.mp3` on the Files page | `brew install ffmpeg` |

SQLite is **not** a separate install. Python and SQLAlchemy use the copy that ships with macOS / Python.

Python packages are **not** listed here. They go in `requirements.txt` and are installed into the venv.

### Check the other Mac

```bash
python3 --version    # need 3.11 or newer
ffmpeg -version      # need ffmpeg, with libmp3lame
ffmpeg -encoders 2>/dev/null | grep libmp3lame
```

If `python3` is missing, install Python. If `ffmpeg` is missing, install [Homebrew](https://brew.sh) if needed, then:

```bash
brew install ffmpeg
```

Homebrew’s ffmpeg includes `libmp3lame`. A custom ffmpeg build without MP3 support will save the `.wav` but fail the conversion.

## Setup on the other computer

```bash
cd /path/to/grok-fastapi

python3 --version    # must be 3.11 or newer, not Apple's 3.9
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./run.sh
```

Always start with `./run.sh` or `./venv/bin/uvicorn ...`. A plain `uvicorn` command often picks up a different Python (this is the `sqlalchemy` error below).

Open http://127.0.0.1:8000

Fresh `data/` (no copied database):

- Username: `admin`
- Password: `root`
- You must change that password before the rest of the site unlocks.

`--reload` is optional and only for development.

### Keep this Mac’s users and files

Copy `data/` next to `app/` on the new computer (same layout: `data/app.db` and `data/uploads/`). Do not copy `venv`. Then run the setup commands above.

## Python packages (`requirements.txt`)

Installed only inside the venv:

- fastapi
- uvicorn
- jinja2
- python-multipart (HTML forms and file uploads)
- sqlalchemy (SQLite)
- bcrypt (password hashes)

`pip install -r requirements.txt` is enough. You do not install those with Homebrew.

## Run later

```bash
cd /path/to/grok-fastapi
./run.sh
```

### `ModuleNotFoundError: No module named 'sqlalchemy'`

`uvicorn` ran from the wrong Python. The traceback path `Library/Python/3.9/bin/uvicorn` is Apple’s Command Line Tools Python, not the project venv.

Fix:

```bash
cd /path/to/grok-fastapi
python3 --version                 # 3.11+
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python -c "import sqlalchemy, fastapi; print('ok')"
./run.sh
```

`which uvicorn` should print `.../grok-fastapi/venv/bin/uvicorn`, not `Library/Python/3.9/...`.

Uploads live in `data/uploads/<username>/`. The user database is `data/app.db`.
