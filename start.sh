#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [[ -f "${PROJECT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.env"
  set +a
fi

VENV_PY="${PROJECT_DIR}/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "Virtual environment not found at ${PROJECT_DIR}/.venv. Run ./install.sh first." >&2
  exit 1
fi

HEADLESS_VAL="${DUCK_API_BROWSER_HEADLESS:-true}"
if [[ "${HEADLESS_VAL,,}" == "false" ]] && [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  if command -v xvfb-run >/dev/null 2>&1; then
    exec xvfb-run -a -s "-screen 0 1366x900x24" "$VENV_PY" -m app
  else
    echo "DUCK_API_BROWSER_HEADLESS=false requires DISPLAY, WAYLAND_DISPLAY, or xvfb-run." >&2
    exit 1
  fi
fi

exec "$VENV_PY" -m app
