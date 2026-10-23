from __future__ import annotations

import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, func, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def uid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    password: Mapped[str] = mapped_column(String)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Admin(Base):
    __tablename__ = "administrators"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String, unique=True)
    password: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    realm: Mapped[str] = mapped_column(String, default="product")
    expires_at: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Member(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String, default="viewer")
    decision_role: Mapped[str] = mapped_column(String, default="ceo")


class Item(Base):
    """Versionable workspace records: sources, evidence, events, briefs, feedback and alerts."""
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String, default=uid)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now, index=True)
    updated_at: Mapped[str] = mapped_column(String, default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String, default=now)
    started_at: Mapped[str] = mapped_column(String, default="")
    finished_at: Mapped[str] = mapped_column(String, default="")


class Audit(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String, default="", index=True)
    actor_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Usage(Base):
    __tablename__ = "model_usage"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, default="")
    purpose: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now)


db_url = os.environ.get("DATABASE_URL", "sqlite:///./.local/signaldesk.sqlite")
if db_url.startswith("sqlite"):
    Path(db_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(db_url, connect_args={"check_same_thread": False, "timeout": 30} if db_url.startswith("sqlite") else {}, pool_pre_ping=True)
if db_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")

DB = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with DB() as db:
        yield db


def patch_json(db, row, field, changes):
    """Merge worker metadata without replacing preferences edited during a long run."""
    if db.bind.dialect.name == "sqlite":
        column = getattr(type(row), field)
        merged = func.coalesce(column, "{}")
        for key, value in changes.items():
            merged = func.json_set(merged, "$." + key, func.json(json.dumps(value)))
        db.execute(update(type(row)).where(type(row).id == row.id).values({field: merged}), execution_options={"synchronize_session": False})
        db.refresh(row, attribute_names=[field])
    else:
        db.refresh(row, with_for_update=True)
        setattr(row, field, {**getattr(row, field), **changes})
        db.flush()


def items(db, wid: str, kind: str):
    return db.query(Item).filter_by(workspace_id=wid, kind=kind).order_by(Item.created_at.desc()).all()


def record(db, wid: str, kind: str, payload: dict, key: str | None = None):
    row = db.query(Item).filter_by(workspace_id=wid, kind=kind, key=key).first() if key else None
    if row:
        row.payload = payload
        row.updated_at = now()
    else:
        row = Item(workspace_id=wid, kind=kind, payload=payload, **({"key": key} if key else {}))
        db.add(row)
    db.flush()
    return row


def pack(row):
    return {**row.payload, "id": row.id, "created_at": row.created_at, "updated_at": row.updated_at}


def audit(db, actor, action, wid="", **detail):
    db.add(Audit(workspace_id=wid, actor_id=actor, action=action, detail=detail))
