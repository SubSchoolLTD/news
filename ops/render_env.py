"""Render production runtime environment to stdout; pipe directly to SSH, never logs."""
import os
import sys

required = ["APP_SECRET", "ALFA_API_KEY", "SENDPULSE_ID", "SENDPULSE_SECRET", "ADMIN_EMAIL", "ADMIN_PASSWORD"]
missing = [k for k in required if not os.getenv(k)]
if missing:
    sys.exit("Missing deployment secrets: " + ", ".join(missing))
values = {
    "APP_ENV": "production", "COOKIE_SECURE": "true", "PUBLIC_URL": "https://analytics.subschool.us",
    "ALLOWED_ORIGINS": "https://analytics.subschool.us,https://analytics.subschool.ru",
    "DATABASE_URL": "sqlite:////data/signaldesk.sqlite", "ALFA_BASE_URL": "https://changellenge.up.railway.app/v1",
    "ALFA_FALLBACK_URL": "https://api.alfahack-gateway26.ru/v1", "ALFA_MODEL": "qwen/qwen3.6-35b-a3b",
    "EMAIL_FROM": "maksim@subschool.us", "EMAIL_DELIVERY": "sendpulse", "WORKER_ENABLED": "true",
    "MODEL_DAILY_TOKEN_LIMIT": "240000", **{k: os.environ[k] for k in required},
}
for name, value in values.items():
    if "\n" in value or "\r" in value:
        sys.exit("Deployment secrets must be single-line values.")
    print(name + "='" + value.replace("\\", "\\\\").replace("'", "\\'") + "'")
