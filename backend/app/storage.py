"""Transactional local demo state shared by API and dashboard processes.

The legacy JSON file is imported once, without deleting it. A single SQLite
row keeps the small demo state together while avoiding lost read/write updates.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def empty_state():
    return {"decisions": {}, "outcomes": {}, "outcome_decisions": {}, "messages": {}, "events": {}}


@contextmanager
def _connection(legacy_path):
    legacy_path = Path(legacy_path)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(legacy_path.with_suffix(".sqlite3"), timeout=30)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
        if not connection.execute("SELECT 1 FROM app_state WHERE id=1").fetchone():
            initial = empty_state()
            if legacy_path.exists():
                legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
                for key in initial:
                    if key in legacy:
                        if not isinstance(legacy[key], dict):
                            raise ValueError(f"Invalid legacy state field: {key}")
                        initial[key] = legacy[key]
            connection.execute("INSERT OR IGNORE INTO app_state VALUES (1, ?)",
                               (json.dumps(initial, ensure_ascii=False),))
            connection.commit()
        yield connection
    finally:
        connection.close()


def read_state(path):
    with _connection(path) as connection:
        return json.loads(connection.execute("SELECT payload FROM app_state WHERE id=1").fetchone()[0])


@contextmanager
def transaction(path):
    with _connection(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        state = json.loads(connection.execute("SELECT payload FROM app_state WHERE id=1").fetchone()[0])
        try:
            yield state
            connection.execute("UPDATE app_state SET payload=? WHERE id=1",
                               (json.dumps(state, ensure_ascii=False),))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
