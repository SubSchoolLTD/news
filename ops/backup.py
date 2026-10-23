"""Consistent SQLite backup: run inside the app container. Keeps the newest 14."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

directory=Path('/data/backups')
directory.mkdir(exist_ok=True)
target=directory/f"signaldesk-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.sqlite"
with sqlite3.connect('/data/signaldesk.sqlite') as source, sqlite3.connect(target) as backup:
    source.backup(backup)
for old in sorted(directory.glob('signaldesk-*.sqlite'),reverse=True)[14:]:
    old.unlink()
print(target.name)
