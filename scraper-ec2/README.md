# Meesho Seller Central — EC2 Worker (Labels + Payments Auto-fetch)

Runs on **Ubuntu 26.04 EC2**. Polls the same MongoDB the dashboard uses, picks up `label_download` and `payments_fetch` jobs, dispatches them per-account.

## Architecture (recap)

```
EC2 Ubuntu
├── Multiple Chrome processes (one per supplier account)
│      port 9222 → /home/ubuntu/chrome-profile1   (Account "hrbib")
│      port 9223 → /home/ubuntu/chrome-profile2   (Account "uobfs")
├── label_worker.py        ← single dispatcher for both job types
├── labels.py              ← label-download flow (CDP-attached)
├── payments_fetcher.py    ← payments xlsx download flow (CDP-attached)
└── systemd: meesho-label-worker.service
```

## Files

| File | Purpose |
|---|---|
| `labels.py` | Your latest label-download bot. Globals overridden per-account by the dispatcher. |
| `payments_fetcher.py` | Drives the Meesho Payments page → Download → Payments to Date → period radio → unzips → POSTs xlsx to dashboard `/api/pl/upload`. |
| `label_worker.py` | Single polling loop that handles both `label_download` and `payments_fetch` jobs. |
| `start_chromes.sh` | Reads enabled accounts from MongoDB and launches one Chrome each. |
| `install.sh` | One-time install: deps + systemd unit. |
| `meesho-label-worker.service` | systemd unit. |

## One-time setup

1. **Copy this whole folder to the EC2 instance**, e.g. via `scp`:
   ```
   scp -r scraper-ec2/ ubuntu@<ec2-ip>:~/
   ssh ubuntu@<ec2-ip>
   cd scraper-ec2
   chmod +x install.sh start_chromes.sh
   ./install.sh
   ```

2. **Add accounts** via the dashboard's Accounts page *(once that's wired)* or via the seed Python in `install.sh` output.

   Per account, store: `name`, `debug_port`, `profile_dir`, `pending_url`, `ready_url`, `enabled`.

3. **Launch Chromes** (run this whenever the EC2 reboots — or wire it into systemd separately):
   ```
   cd ~/meesho-label-worker
   ./start_chromes.sh
   ```

4. **Log in to supplier.meesho.com once per Chrome**.
   Easiest path on a headless EC2:
   - Install a small VNC server (`xfce4 + tightvncserver`) OR
   - Use Chrome Remote Desktop OR
   - `ssh -L 9222:127.0.0.1:9222 ubuntu@<ec2-ip>` and connect from your local laptop's Chrome dev-tools to the remote port.
   - Once logged in, the session persists in `/home/ubuntu/chrome-profile<N>`. Subsequent runs reuse it.

5. **Start the systemd service:**
   ```
   sudo systemctl start meesho-label-worker
   sudo systemctl status meesho-label-worker
   tail -f /var/log/meesho-label-worker.log
   ```

## Day-to-day

- **Labels** — submit from the dashboard → backend creates a `label_download` job → worker picks it up.
- **Payments auto-fetch** — backend cron enqueues `payments_fetch` jobs:
   - **Every Monday 09:00 IST** → period = `previous_week`
   - **Every 5th of month 09:00 IST** → period = `previous_month`
- **Manual on-demand fetch** — Uploads page → "Fetch latest now" button (period dropdown).
- The worker opens the supplier panel for the account, clicks `Download → Payments to Date → <period> → Download`, waits for the .zip, extracts the .xlsx, and POSTs it to `/api/pl/upload`. Job moves to `done` automatically.

### Required env on the worker

| Var | Example | Purpose |
|---|---|---|
| `MESHO_MONGO_URI` | `mongodb://43.205.229.129:27017/` | Same Mongo as dashboard |
| `MESHO_DB_NAME` | `meesho` | |
| `DASHBOARD_URL` | `http://127.0.0.1:8000` | Where the worker POSTs xlsx (your dashboard backend on the same EC2) |
| `WORKER_API_KEY` | — | **Must match** `WORKER_API_KEY` in `/app/backend/.env`. Already pre-generated in the dashboard `.env`; copy that string into `meesho-label-worker.service`. |
| `MESHO_DOWNLOAD_DIR` | `/home/ubuntu/meesho-downloads` | Where Chrome drops the .zip and we extract the xlsx (auto-cleaned). |

After editing `meesho-label-worker.service`, run:
```
sudo systemctl daemon-reload
sudo systemctl restart meesho-label-worker
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Job fails: `Chrome not running on port 9222` | Run `./start_chromes.sh`, or check `tail /tmp/chrome-9222.log`. |
| Chrome launched but supplier portal asks for login again | Profile dir got recreated. Log in once more, session persists from then on. |
| Jobs stay `pending` | `sudo systemctl status meesho-label-worker` — service may have crashed. Check `/var/log/meesho-label-worker.log`. |
| Wrong account picked up the job | Inspect `accounts` docs in Mongo: `db.accounts.find()`. Each label job carries `account_id` matching one of those. |

## Manual run (without systemd)

```
cd /home/ubuntu/meesho-label-worker
MESHO_MONGO_URI=mongodb://43.205.229.129:27017/ python3 label_worker.py
```
