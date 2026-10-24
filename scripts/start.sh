#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python -m gunicorn --preload --bind "0.0.0.0:${PORT:-3000}" --workers "${WEB_CONCURRENCY:-2}" --timeout 60 --access-logfile - --error-logfile - wsgi:app
