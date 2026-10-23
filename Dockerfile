FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://registry.npmjs.org
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && useradd --uid 10001 --create-home signaldesk && mkdir /data && chown signaldesk:signaldesk /data
COPY --chown=signaldesk:signaldesk backend/ /app/backend/
COPY --chown=signaldesk:signaldesk data/ /app/data/
COPY --chown=signaldesk:signaldesk ops/ /app/ops/
COPY --from=frontend --chown=signaldesk:signaldesk /build/dist/ /app/frontend/dist/
USER signaldesk
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
