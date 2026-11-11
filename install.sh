#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"

HOST="127.0.0.1"
PORT="8000"
API_KEY=""
GENERATE_KEY="false"
HEADLESS="false"
INSTALL_DEPS="true"
INSTALL_XVFB="true"
SETUP_SYSTEMD="false"
NON_INTERACTIVE="false"
NO_SANDBOX="false"

usage() {
  cat <<'EOF'
duck-to-api Linux Installer

Usage:
  ./install.sh [options]

Options:
  --host <ip>           Bind address (default: 127.0.0.1, use 0.0.0.0 for LAN)
  --port <port>         Listen port (default: 8000)
  --api-key <key>       Set DUCK_API_API_KEY in .env
  --generate-key        Auto-generate a random API key if --api-key is omitted
  --headless <bool>     Browser headless mode (default: false; uses Xvfb if no DISPLAY)
  --skip-deps           Skip Playwright OS dependency installation (playwright install-deps)
  --skip-xvfb           Skip Xvfb package installation on headless Linux servers
  --systemd             Install and enable a systemd service unit
  --no-sandbox          Set DUCK_API_CHROMIUM_NO_SANDBOX=true (helpful in containers)
  --non-interactive     Do not prompt for confirmation
  -h, --help            Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --api-key) API_KEY="$2"; shift 2 ;;
    --generate-key) GENERATE_KEY="true"; shift ;;
    --headless) HEADLESS="$2"; shift 2 ;;
    --skip-deps) INSTALL_DEPS="false"; shift ;;
    --skip-xvfb) INSTALL_XVFB="false"; shift ;;
    --systemd) SETUP_SYSTEMD="true"; shift ;;
    --no-sandbox) NO_SANDBOX="true"; shift ;;
    --non-interactive) NON_INTERACTIVE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

log() { printf '[duck-to-api] %s\n' "$*"; }
warn() { printf '[duck-to-api] WARNING: %s\n' "$*" >&2; }
die() { printf '[duck-to-api] ERROR: %s\n' "$*" >&2; exit 1; }

run_privileged() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "Root privileges or sudo required to run: $*"
  fi
}

find_python() {
  local candidates=(python3.14 python3.13 python3.12 python3.11 python3)
  for cmd in "${candidates[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      if "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  die "Python 3.11+ is required. Install python3.11+ and python3-venv (e.g. 'sudo apt update && sudo apt install -y python3 python3-venv python3-pip') and re-run."
fi
log "Using Python: $("$PYTHON_BIN" --version) ($PYTHON_BIN)"

if [[ ! -d "$VENV_DIR" ]]; then
  log "Creating virtual environment at ${VENV_DIR}..."
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    die "Failed to create venv. On Debian/Ubuntu install python3-venv: sudo apt install -y python3-venv"
  fi
fi

VENV_PY="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"

log "Upgrading pip and installing duck-to-api..."
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PIP" install -e "${PROJECT_DIR}[dev]"

if [[ "$INSTALL_DEPS" == "true" ]]; then
  log "Installing Chromium OS libraries via Playwright..."
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$VENV_PY" -m playwright install-deps chromium
  elif command -v sudo >/dev/null 2>&1; then
    if [[ "$NON_INTERACTIVE" == "true" ]]; then
      sudo -n "$VENV_PY" -m playwright install-deps chromium || warn "sudo non-interactive failed; run 'sudo ${VENV_PY} -m playwright install-deps chromium' manually if Chromium lacks shared libraries."
    else
      sudo "$VENV_PY" -m playwright install-deps chromium
    fi
  else
    warn "sudo not found; skipping OS library installation. Run '${VENV_PY} -m playwright install-deps chromium' as root if needed."
  fi
fi

log "Installing Playwright Chromium browser..."
"$VENV_PY" -m playwright install chromium

if [[ "$INSTALL_XVFB" == "true" ]] && ! command -v xvfb-run >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing xvfb so headed Chromium works on headless Linux servers..."
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      apt-get update -qq && apt-get install -y -qq xvfb || warn "Could not install xvfb automatically."
    elif command -v sudo >/dev/null 2>&1; then
      if [[ "$NON_INTERACTIVE" == "true" ]]; then
        sudo -n apt-get update -qq && sudo -n apt-get install -y -qq xvfb || warn "Could not install xvfb automatically."
      else
        sudo apt-get update -qq && sudo apt-get install -y -qq xvfb || warn "Could not install xvfb automatically."
      fi
    fi
  elif command -v dnf >/dev/null 2>&1; then
    run_privileged dnf install -y xorg-x11-server-Xvfb || warn "Could not install xorg-x11-server-Xvfb automatically."
  elif command -v pacman >/dev/null 2>&1; then
    run_privileged pacman -Sy --noconfirm xorg-server-xvfb || warn "Could not install xorg-server-xvfb automatically."
  fi
fi

mkdir -p "${PROJECT_DIR}/data/browser_profile" "${PROJECT_DIR}/data/uploads" "${PROJECT_DIR}/data/outputs"

if [[ "$GENERATE_KEY" == "true" && -z "$API_KEY" ]] || [[ "$HOST" == "0.0.0.0" && -z "$API_KEY" && ! -f "${PROJECT_DIR}/.env" ]]; then
  API_KEY="$("$VENV_PY" -c 'import secrets; print(secrets.token_hex(24))')"
  log "Generated DUCK_API_API_KEY for LAN protection: ${API_KEY}"
fi

ENV_FILE="${PROJECT_DIR}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  log "Creating ${ENV_FILE}..."
  "$VENV_PY" - "$PROJECT_DIR" "$HOST" "$PORT" "$API_KEY" "$HEADLESS" "$NO_SANDBOX" <<'PYEOF'
import pathlib, sys

project_dir, host, port, api_key, headless, no_sandbox = sys.argv[1:7]
root = pathlib.Path(project_dir)
example = (root / ".env.example").read_text(encoding="utf-8")
overrides = {
    "DUCK_API_HOST": host,
    "DUCK_API_PORT": port,
    "DUCK_API_API_KEY": api_key,
    "DUCK_API_BROWSER_HEADLESS": headless,
    "DUCK_API_CHROMIUM_NO_SANDBOX": no_sandbox,
}
lines = []
seen = set()
for line in example.splitlines():
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in line:
        k = line.split("=", 1)[0].strip()
        if k in overrides:
            lines.append(f"{k}={overrides[k]}")
            seen.add(k)
            continue
    lines.append(line)
for k, v in overrides.items():
    if k not in seen:
        lines.append(f"{k}={v}")
(root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
PYEOF
else
  log "Existing ${ENV_FILE} preserved."
fi

chmod +x "${PROJECT_DIR}/start.sh" "${PROJECT_DIR}/install.sh"

if [[ "$SETUP_SYSTEMD" == "true" ]]; then
  SERVICE_USER="${SUDO_USER:-$(id -un)}"
  SERVICE_FILE="/etc/systemd/system/duck-to-api.service"
  log "Installing systemd unit at ${SERVICE_FILE} (user=${SERVICE_USER})..."
  TMP_UNIT="$(mktemp)"
  cat >"$TMP_UNIT" <<EOF
[Unit]
Description=duck-to-api Browser-to-OpenAI Image Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${PROJECT_DIR}/start.sh
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
  run_privileged cp "$TMP_UNIT" "$SERVICE_FILE"
  rm -f "$TMP_UNIT"
  run_privileged systemctl daemon-reload
  run_privileged systemctl enable --now duck-to-api.service
  log "systemd service enabled and started. Check logs with: sudo journalctl -u duck-to-api -f"
fi

log "Running post-install import verification..."
"$VENV_PY" -c "import app.main, playwright, fastapi; print('duck-to-api install verified')"

cat <<EOF

Installation complete.
- Start manually: ${PROJECT_DIR}/start.sh
- Dashboard URL:  http://${HOST}:${PORT}/
- OpenAPI Docs:   http://${HOST}:${PORT}/docs
EOF
