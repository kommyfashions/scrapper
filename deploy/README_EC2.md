# Meesho Seller Dashboard — EC2 Deployment Guide

This deploys the **dashboard (FastAPI + React)** on Ubuntu EC2.
The product scraper stays on your **local Windows** machine, untouched.
The label worker (already deployed on EC2 separately) continues to run.

```
┌─────────────────────────────────────────────────────────────┐
│ Ubuntu EC2 (single instance)                                │
│                                                             │
│   nginx :80  ──┬──>  static files  /home/.../frontend/build │
│                └──>  /api/*  ──>  uvicorn 127.0.0.1:8001    │
│                                                             │
│   mongod :27017  <──  backend, label_worker, this dashboard │
│                                                             │
│   meesho-label-worker.service   (you already have this)     │
│   meesho-dashboard-backend.service (NEW — this guide)       │
└─────────────────────────────────────────────────────────────┘

  Local Windows
    └── product_review.py + worker.py  ──>  EC2 Mongo @ port 27017
```

---

## 0. Prerequisites on EC2

- Ubuntu 22.04 / 24.04 / 26.04
- Security group allows inbound **TCP 80** (HTTP) and **TCP 22** (SSH).
- MongoDB already running on the same EC2 at `127.0.0.1:27017` (you already have this).
  - If MongoDB is bound only to localhost, your **local Windows** scraper needs port `27017` open in the SG and `bindIp` set to `0.0.0.0` in `/etc/mongod.conf`. (You already do this — keep your existing setup.)
- A user `ubuntu` with sudo. (Default Ubuntu AMI user.)

---

## 1. Get the code onto EC2

Pick one of:

### Option A — Save to GitHub (from this Emergent chat) and clone
1. In the Emergent chat input, click **Save to GitHub** and push to a private repo.
2. On EC2:
   ```bash
   cd /home/ubuntu
   git clone git@github.com:<you>/<repo>.git meesho-dashboard
   ```

### Option B — rsync from your laptop
From your laptop where you have the code:
```bash
rsync -avz --exclude node_modules --exclude .venv --exclude __pycache__ \
      ./app/ ubuntu@<ec2-ip>:/home/ubuntu/meesho-dashboard/
```

After this, `/home/ubuntu/meesho-dashboard/` should contain at minimum:
```
backend/   frontend/   deploy/   scraper-ec2/   memory/
```

---

## 2. Run the installer (one command)

```bash
cd /home/ubuntu/meesho-dashboard/deploy
chmod +x install.sh
./install.sh
```

The installer will:
- Install python3, node 20, yarn, nginx
- Create a Python venv in `backend/.venv` and install requirements
- Create `backend/.env` (with placeholder secrets) **only if it doesn't exist**
- Build the React frontend (`yarn build`)
- Install the systemd unit `meesho-dashboard-backend.service`
- Install the nginx site and reload nginx

---

## 3. Edit secrets and restart

Open `/home/ubuntu/meesho-dashboard/backend/.env` and **change at minimum**:

```env
JWT_SECRET=<run: openssl rand -hex 32>
ADMIN_PASSWORD=<your strong password>
ADMIN_EMAIL=<your admin email>
```

Then restart:
```bash
sudo systemctl restart meesho-dashboard-backend
```

> Whenever you change `ADMIN_PASSWORD` in `.env`, the backend re-hashes it on next startup so login stays in sync.

---

## 4. Open the dashboard

```
http://<your-ec2-public-ip>/
```

Login with the admin email/password you put in `.env`.

The accounts you already created in the previous deployment will be visible (they live in MongoDB, not in code).

---

## 5. Verify everything is wired up

```bash
# backend health
curl http://127.0.0.1:8001/api/health
# expected: {"ok":true}

# nginx → backend
curl http://localhost/api/health
# expected: {"ok":true}

# backend logs (live)
sudo journalctl -u meesho-dashboard-backend -f

# nginx access/errors
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

---

## 6. Optional: HTTPS with Let's Encrypt

If you have a domain pointing at the EC2 public IP:
```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```
Certbot edits the nginx config in place; nothing else to do.

---

## 7. Day-to-day commands

| Action | Command |
|---|---|
| Pull new code | `cd /home/ubuntu/meesho-dashboard && git pull` |
| Reinstall backend deps | `source backend/.venv/bin/activate && pip install -r backend/requirements.txt && deactivate` |
| Rebuild frontend | `cd frontend && yarn build` |
| Restart backend | `sudo systemctl restart meesho-dashboard-backend` |
| Reload nginx | `sudo systemctl reload nginx` |
| Backend logs | `sudo journalctl -u meesho-dashboard-backend -n 200 -f` |
| Worker (labels) logs | `sudo journalctl -u meesho-label-worker -f` |

A typical "deploy a code change" loop:
```bash
cd /home/ubuntu/meesho-dashboard
git pull
cd frontend && yarn build && cd ..
sudo systemctl restart meesho-dashboard-backend
sudo systemctl reload nginx
```

---

## 8. Local Windows scraper — no change needed

Your `product_review.py` + `worker.py` continue to run on Windows and connect to the same MongoDB at `mongodb://<ec2-public-ip>:27017/` (or VPN/private IP). The new P&L feature only adds new collections (`pl_orders`, `pl_sku_costs`, `pl_uploads`, `pl_ads_cost`) — your scraper writes to the existing `products` and `jobs` collections, so it is **completely unaffected**.

---

## 9. Common issues

- **`502 Bad Gateway`** in browser → backend is down. Check `sudo journalctl -u meesho-dashboard-backend -n 100`.
- **`Login failed`** → `.env` `ADMIN_PASSWORD` mismatched or `JWT_SECRET` empty. Restart backend after editing.
- **Upload returns `502` for big files** → bump `client_max_body_size` in `nginx-meesho-dashboard.conf` (default 50M is fine for ≤10k orders).
- **Frontend shows blank or 404 on refresh** → `try_files $uri /index.html;` rule missing; reinstall nginx config.
- **`Cannot connect to MongoDB`** → check `MONGO_URL` in `backend/.env` and that mongod is running: `sudo systemctl status mongod`.

---

## 10. File map of `/home/ubuntu/meesho-dashboard`

```
backend/
  server.py
  requirements.txt
  .env                      ← you create this (or installer does)
  .venv/                    ← python venv (created by installer)
frontend/
  build/                    ← created by `yarn build`, served by nginx
  src/, package.json, ...
deploy/
  install.sh                ← run this
  meesho-dashboard-backend.service
  nginx-meesho-dashboard.conf
  README_EC2.md             ← this file
scraper-ec2/                ← unchanged label worker (already running)
```
