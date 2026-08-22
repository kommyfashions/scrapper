#!/usr/bin/env bash
# =====================================================================
#  update.sh — re-sync the EC2 label-worker after a `git pull`.
#
#  Run this from the folder containing your freshly-pulled scraper-ec2
#  files (i.e. the same folder that has label_worker.py, install.sh,
#  and all the *_fetcher.py files).
#
#  What it does:
#    1. Copies every *.py / *.sh into /home/ubuntu/meesho-label-worker/
#    2. Restarts the systemd service
#    3. Prints the last 20 log lines so you can see JOB_TYPES=[...] and
#       confirm the new fetchers are loaded.
#
#  Typical workflow after a dashboard release:
#    cd ~/scrapper && git pull origin main
#    cd scraper-ec2 && sudo bash update.sh
# =====================================================================
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/home/ubuntu/meesho-label-worker}"
SUDO=""
[[ $EUID -ne 0 ]] && SUDO="sudo"

if ! ls *.py >/dev/null 2>&1; then
    echo "❌ No *.py files found in $(pwd)"
    echo "   Run update.sh from inside scraper-ec2/ after 'git pull'."
    exit 1
fi

echo "==> Syncing files to ${INSTALL_DIR}…"
${SUDO} mkdir -p "${INSTALL_DIR}"
${SUDO} cp -v *.py *.sh "${INSTALL_DIR}/"
${SUDO} chmod +x "${INSTALL_DIR}/"*.sh

echo "==> Restarting systemd service…"
${SUDO} systemctl restart meesho-label-worker.service

sleep 2
echo "==> Last 20 log lines:"
${SUDO} tail -n 20 /var/log/meesho-label-worker.log || true

echo ""
echo "✅ Update complete."
echo "   Verify JOB_TYPES include 'inventory_sync' and 'accept_labels':"
echo "     grep types /var/log/meesho-label-worker.log | tail -1"
