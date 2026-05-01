# Meesho Seller Central — EC2 Label Download Worker

Runs on **Ubuntu 26.04 EC2**. Polls the same MongoDB the dashboard uses, picks up `label_download` jobs, dispatches them per-account.

## Architecture (recap)

```
EC2 Ubuntu
├── Multiple Chrome processes (one per supplier account)
│      port 9222 → /home/ubuntu/chrome-profile1   (Account "Main")
│      port 9223 → /home/ubuntu/chrome-profile2   (Account "Brand B")
├── label_worker.py  ← polls jobs, picks the right Chrome by account_id
└── systemd: meesho-label-worker.service
```

## Files

| File | Purpose |
|---|---|
| `labels.py` | Your latest bot (verbatim). Globals `DEBUG_PORT`, `PENDING_URL`, `READY_URL` are overridden per-account by `label_worker.py`. |
| `label_worker.py` | Polls MongoDB, attaches via CDP to the account's port, calls `labels.main()`. |
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

- Submit a label run from the dashboard → backend creates a `label_download` job with the chosen `account_id`.
- The systemd worker picks it up within ~5s, attaches to the right Chrome port, runs `labels.main()`.
- Job moves to `done` (or `failed` with the full error text).

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
