"""Create a verified reviewer from the local console when SMTP is disabled.

This command is deliberately unavailable in production. It changes no HTTP
authentication rules, creates no sample events and never resets an existing user.
"""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main():
    if os.getenv("APP_ENV", "development") not in {"development", "test"}:
        raise SystemExit("Local reviewer creation is disabled outside development/test.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Local reviewer")
    parser.add_argument("--password-stdin", action="store_true", help="Read one password line from stdin for local automation.")
    args = parser.parse_args()
    email = args.email.strip().lower()
    if "@" not in email or len(email) > 254 or any(c.isspace() for c in email):
        raise SystemExit("Use a valid email address.")
    password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("Choose a local password (12+ characters): ")
    if len(password) < 12:
        raise SystemExit("The password must contain at least 12 characters.")
    if not args.password_stdin and getpass.getpass("Repeat password: ") != password:
        raise SystemExit("Passwords do not match.")
    from app.db import Base, DB, User, engine
    from app.security import hasher

    Base.metadata.create_all(engine)
    with DB() as db:
        if db.query(User).filter_by(email=email).first():
            raise SystemExit("This account already exists; no account was changed.")
        db.add(User(email=email, name=args.name.strip() or "Local reviewer", password=hasher.hash(password), verified=True, preferences={"email_alerts": False, "email_briefs": False}))
        db.commit()
    print(f"Local reviewer created: {email}. Sign in with the password you chose.")


if __name__ == "__main__":
    main()
