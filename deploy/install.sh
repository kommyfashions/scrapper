#!/usr/bin/env bash
# =====================================================================
#  install.sh — one-shot install of meesho-dashboard on Ubuntu EC2
#
#  Run from inside this folder (deploy/) on the EC2 box. Idempotent.
#
#  Defaults assume:
#    - MongoDB already running on the same EC2 at 127.0.0.1:27017
#    - Source code lives at /home/ubuntu/meesho-dashboard (rsync'd or git clone)
#    - You will reverse-proxy via nginx on port 80
# =====================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/meesho-dashboard}"
SUDO=""
[[ $EUID -ne 0 ]] && SUDO="sudo"

echo "==> Updating apt"
${SUDO} apt-get update -y

echo "==> Installing system deps (python, node, nginx, mongodb-tools)"
${SUDO} apt-get install -y python3 python3-pip python3-venv nginx curl gnupg ca-certificates

if ! command -v node >/dev/null 2>&1; then
  echo "==> Installing Node.js 20"
  curl -fsSL https://deb.nodesource.com/setup_20.x | ${SUDO} -E bash -
  ${SUDO} apt-get install -y nodejs
fi
if ! command -v yarn >/dev/null 2>&1; then
  echo "==> Installing yarn"
  ${SUDO} npm install -g yarn
fi

# -------- Backend --------
echo "==> Setting up backend venv"
cd "${APP_DIR}/backend"

if [ ! -f "${APP_DIR}/backend/.env" ]; then
  echo "==> Creating backend/.env from template (EDIT THIS!)"
  cat > "${APP_DIR}/backend/.env" <<'ENV'
MONGO_URL=mongodb://127.0.0.1:27017
DB_NAME=meesho
JWT_SECRET=CHANGE_ME_TO_A_LONG_RANDOM_STRING
ADMIN_EMAIL=admin@meesho-dash.local
ADMIN_PASSWORD=CHANGE_ME
CORS_ORIGINS=*
STUCK_JOB_MINUTES=30
ENV
  echo "    >>> EDIT ${APP_DIR}/backend/.env BEFORE THE BACKEND IS USABLE <<<"
fi

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
# Use the slim production list, not the bloated dev pip-freeze
pip install -r "${APP_DIR}/deploy/requirements-prod.txt"
deactivate

# -------- Frontend (build) --------
echo "==> Building frontend"
cd "${APP_DIR}/frontend"
if [ ! -f ".env" ]; then
  echo 'REACT_APP_BACKEND_URL=' > .env  # same-origin: API resolves to /api
fi
yarn install --frozen-lockfile
yarn build

# -------- systemd service --------
echo "==> Installing systemd unit for the backend"
cd "${APP_DIR}/deploy"
${SUDO} cp -v meesho-dashboard-backend.service /etc/systemd/system/meesho-dashboard-backend.service
${SUDO} systemctl daemon-reload
${SUDO} systemctl enable meesho-dashboard-backend.service
${SUDO} systemctl restart meesho-dashboard-backend.service

# -------- nginx --------
echo "==> Installing nginx site"
${SUDO} cp -v nginx-meesho-dashboard.conf /etc/nginx/sites-available/meesho-dashboard
${SUDO} ln -sf /etc/nginx/sites-available/meesho-dashboard /etc/nginx/sites-enabled/meesho-dashboard
${SUDO} rm -f /etc/nginx/sites-enabled/default
${SUDO} nginx -t
${SUDO} systemctl reload nginx

cat <<EOF

==================================================================
Install complete.
==================================================================
Open the dashboard:    http://<your-ec2-public-ip>/
Admin credentials:     see ${APP_DIR}/backend/.env

Useful commands:
  Backend logs:        sudo journalctl -u meesho-dashboard-backend -f
  Backend restart:     sudo systemctl restart meesho-dashboard-backend
  Nginx logs:          sudo tail -f /var/log/nginx/error.log
  Health check:        curl http://127.0.0.1:8001/api/health

If you change backend/.env:
  sudo systemctl restart meesho-dashboard-backend

If you change frontend code:
  cd ${APP_DIR}/frontend && yarn build && sudo systemctl reload nginx
==================================================================
EOF
