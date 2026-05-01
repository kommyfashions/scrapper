#!/usr/bin/env bash
# =====================================================================
#  start_chromes.sh
#  Launches one google-chrome process per ENABLED account in MongoDB.
#  Reads accounts from the EC2 MongoDB and starts Chrome on each
#  account's configured port + profile_dir.
# =====================================================================
set -euo pipefail

MONGO_URI="${MESHO_MONGO_URI:-mongodb://43.205.229.129:27017/}"
DB_NAME="${MESHO_DB_NAME:-meesho}"

CHROME_BIN="$(command -v google-chrome || command -v google-chrome-stable || true)"
if [[ -z "${CHROME_BIN}" ]]; then
    echo "❌ google-chrome not found. Install with: sudo apt install google-chrome-stable"
    exit 1
fi

# Read enabled accounts via Python (PyMongo)
mapfile -t ACCOUNTS < <(python3 - <<PY
from pymongo import MongoClient
import os, json
c = MongoClient(os.environ.get("MESHO_MONGO_URI", "${MONGO_URI}"))
db = c[os.environ.get("MESHO_DB_NAME", "${DB_NAME}")]
for a in db.accounts.find({"enabled": True}):
    print(json.dumps({
        "name": a.get("name"),
        "port": a.get("debug_port"),
        "dir":  a.get("profile_dir"),
    }))
PY
)

if [[ ${#ACCOUNTS[@]} -eq 0 ]]; then
    echo "⚠️ No enabled accounts found in MongoDB. Add some via the dashboard or seed script."
    exit 0
fi

for line in "${ACCOUNTS[@]}"; do
    NAME=$(echo "$line" | python3 -c "import sys,json;print(json.load(sys.stdin)['name'])")
    PORT=$(echo "$line" | python3 -c "import sys,json;print(json.load(sys.stdin)['port'])")
    DIR=$(echo  "$line" | python3 -c "import sys,json;print(json.load(sys.stdin)['dir'])")

    if curl -sf -m 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
        echo "✅ '${NAME}' already up on port ${PORT}"
        continue
    fi

    mkdir -p "${DIR}"
    echo "🚀 Launching Chrome for '${NAME}' on port ${PORT} (profile=${DIR})..."
    nohup "${CHROME_BIN}" \
        --remote-debugging-port="${PORT}" \
        --remote-debugging-address=127.0.0.1 \
        --user-data-dir="${DIR}" \
        --no-first-run \
        --no-default-browser-check \
        --disable-features=Translate \
        > "/tmp/chrome-${PORT}.log" 2>&1 &

    sleep 2
done

echo "🏁 Done. Verify: curl -s http://127.0.0.1:9222/json/version"
