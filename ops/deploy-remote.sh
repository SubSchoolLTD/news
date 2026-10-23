#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/apps/news
exec 9>/tmp/signaldesk-deploy.lock
flock -w 600 9
export RELEASE_ID="${RELEASE_ID:-manual}"
test -s .env
sudo docker network inspect caddy_net >/dev/null 2>&1 || sudo docker network create caddy_net
if sudo docker inspect signaldesk_app >/dev/null 2>&1; then
  sudo docker exec signaldesk_app python /app/ops/backup.py || true
fi
previous=$(cat .release 2>/dev/null || true)
sudo env RELEASE_ID="$RELEASE_ID" docker compose build --pull app
sudo env RELEASE_ID="$RELEASE_ID" docker compose up -d --no-deps app
for attempt in $(seq 1 40); do
  if sudo docker exec signaldesk_app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" >/dev/null 2>&1; then
    printf '%s\n' "${RELEASE_ID:-manual}" > .release
    printf '%s\n' "${previous}" > .previous-release
    exit 0
  fi
  sleep 3
done
echo 'Deployment failed health check.' >&2
sudo docker compose logs --tail=80 app
if [ -n "$previous" ]; then
  sudo env RELEASE_ID="$previous" docker compose up -d --no-build app
fi
exit 1
