#!/bin/bash
# install_monitor.sh
# Installs generator_monitor.py as a systemd service that starts at boot.
# Run once on the Raspberry Pi:  sudo bash install_monitor.sh

set -e

SERVICE_NAME="generator-monitor"
SCRIPT_PATH="/home/tomhoag/GenStat/monitoring/generator_monitor.py"
WORKING_DIR="/home/tomhoag/GenStat/monitoring"
RUN_AS="tomhoag"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Preflight checks ──────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root.  Try: sudo bash install_monitor.sh"
    exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
    echo "ERROR: Script not found at $SCRIPT_PATH"
    echo "Check that the repository is cloned to /home/tomhoag/GenStat before running this."
    exit 1
fi

SECRETS_PATH="/home/tomhoag/GenStat/Secrets.xcconfig"
if [[ ! -f "$SECRETS_PATH" ]]; then
    echo "ERROR: Secrets.xcconfig not found at $SECRETS_PATH"
    echo "Copy Secrets.xcconfig.template to Secrets.xcconfig and fill in your Supabase credentials."
    exit 1
fi

PYTHON=$(which python3)
if [[ -z "$PYTHON" ]]; then
    echo "ERROR: python3 not found on PATH"
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
