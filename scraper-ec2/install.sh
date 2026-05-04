#!/usr/bin/env bash
# =====================================================================
#  install.sh — one-time setup on Ubuntu 26.04 EC2
# =====================================================================
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/home/ubuntu/meesho-label-worker}"
SUDO=""
[[ $EUID -ne 0 ]] && SUDO="sudo"

echo "==> Installing system deps (chrome, python3-pip)…"
${SUDO} apt-get update -y
if ! command -v google-chrome >/dev/null 2>&1; then
    echo "==> Installing google-chrome-stable…"
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
    ${SUDO} apt-get install -y /tmp/chrome.deb
    rm /tmp/chrome.deb
fi
${SUDO} apt-get install -y python3-pip curl

echo "==> Installing Python deps (pymongo, playwright, requests)…"
pip3 install --user pymongo playwright requests --break-system-packages

# Playwright browsers — only needed if your labels.py launches its own browser.
# Since we connect_over_cdp to an already-running Chrome, we don't strictly need
# this. Skipping by default.

echo "==> Copying files to ${INSTALL_DIR}…"
mkdir -p "${INSTALL_DIR}"
mkdir -p /home/ubuntu/meesho-downloads
cp -v label_worker.py labels.py payments_fetcher.py start_chromes.sh "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}/start_chromes.sh"

echo "==> Installing systemd unit…"
${SUDO} cp -v meesho-label-worker.service /etc/systemd/system/meesho-label-worker.service
${SUDO} systemctl daemon-reload
${SUDO} systemctl enable meesho-label-worker.service

cat <<EOF

✅ Install done.

Next steps:
  1) Add at least one account from the dashboard (Accounts page),
     OR seed via Python:

     python3 - <<PY
     from pymongo import MongoClient
     from datetime import datetime, timezone
     c = MongoClient("mongodb://43.205.229.129:27017/")
     # The account 'name' is the Meesho URL suffix
     #   (seen in supplier.meesho.com/panel/v3/new/fulfillment/<NAME>/orders/...)
     # e.g. 'hrbib', 'uobfs'.  URLs are derived automatically by label_worker.
     c.meesho.accounts.insert_one({
         "name": "hrbib",
         "slug": "hrbib",
         "debug_port": 9222,
         "profile_dir": "/home/ubuntu/chrome-profile1",
         "enabled": True,
         "created_at": datetime.now(timezone.utc),
     })
     PY

  2) Launch Chromes for all enabled accounts:
        cd ${INSTALL_DIR} && ./start_chromes.sh
     (Open VNC / chrome-remote / GUI ONCE to log in to supplier.meesho.com.
      Session persists in the profile dir.)

  3) Start the systemd service:
        sudo systemctl start meesho-label-worker
        sudo systemctl status meesho-label-worker
        tail -f /var/log/meesho-label-worker.log

EOF
