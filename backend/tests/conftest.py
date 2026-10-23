import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite:///./.local/pytest.sqlite"
os.environ["WORKER_ENABLED"] = "false"
os.environ["EMAIL_DELIVERY"] = "disabled"
os.environ["APP_ENV"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["APP_SECRET"] = "test-secret-never-used-in-production"

from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, DB, User, engine


@pytest.fixture
def client():
    from app.security import _attempts
    _attempts.clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def register(client, email="owner@example.com"):
    r = client.post("/api/auth/register", json={"name": "Test User", "email": email, "password": "correct-test-password-123"})
    assert r.status_code == 200, r.text
    return r.json()


def workspace(client, name="Test Manufacturing"):
    r = client.post("/api/workspaces", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def verify_user(uid):
    with DB() as db:
        db.get(User, uid).verified = True
        db.commit()
