#!/bin/sh
set -e
cd "$(dirname "$0")"

if [ ! -x venv/bin/uvicorn ]; then
  echo "No project venv. From this folder, with Python 3.11 or newer:"
  echo "  python3 -m venv venv"
  echo "  ./venv/bin/pip install -r requirements.txt"
  echo "  ./run.sh"
  exit 1
fi

exec ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8083 "$@"
