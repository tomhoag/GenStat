#!/bin/bash
# install_monitor.sh
# Installs generator_monitor.py as a systemd service that starts at boot.
# Run once on the Raspberry Pi:  sudo bash install_monitor.sh

set -e

# Derive paths from the script's own location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SERVICE_NAME="generator-monitor"
WORKING_DIR="$SCRIPT_DIR"
SCRIPT_PATH="$SCRIPT_DIR/generator_monitor.py"
VENV_DIR="$REPO_DIR/venv"
PYTHON="$VENV_DIR/bin/python"
SECRETS_PATH="$REPO_DIR/Secrets.xcconfig"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Determine the user who owns the repo (don't run the service as root)
RUN_AS="$(stat -c '%U' "$REPO_DIR" 2>/dev/null || stat -f '%Su' "$REPO_DIR")"

# ── Preflight checks ──────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root.  Try: sudo bash install_monitor.sh"
    exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
    echo "ERROR: Script not found at $SCRIPT_PATH"
    exit 1
fi

if [[ ! -f "$SECRETS_PATH" ]]; then
    echo "ERROR: Secrets.xcconfig not found at $SECRETS_PATH"
    echo "Copy Secrets.xcconfig.template to Secrets.xcconfig and fill in your Supabase credentials."
    exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Virtual environment not found at ${VENV_DIR}"
    echo "Create it first:  python3 -m venv ${VENV_DIR} && ${VENV_DIR}/bin/pip install -r ${WORKING_DIR}/requirements.txt"
    exit 1
fi

# ── Write service file ────────────────────────────────────────────────────────

echo "Writing ${SERVICE_FILE}..."

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Kohler Generator Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_AS}
WorkingDirectory=${WORKING_DIR}
ExecStart=${PYTHON} ${SCRIPT_PATH}
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── Enable and start ──────────────────────────────────────────────────────────

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling ${SERVICE_NAME} to start at boot..."
systemctl enable "$SERVICE_NAME"

echo "Starting ${SERVICE_NAME}..."
systemctl restart "$SERVICE_NAME"

# ── Status ────────────────────────────────────────────────────────────────────

echo ""
echo "Done.  Current service status:"
echo ""
systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "To follow logs:  journalctl -u ${SERVICE_NAME} -f"
