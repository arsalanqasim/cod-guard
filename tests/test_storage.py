import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/app"), str(ROOT)]
from scripts.backup_state import snapshot
from decision_events import append_event
from records import StateUnavailable, connect, ensure_seeded
from storage import read_state, transaction


class StorageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "state.json"

    def test_json_and_blob_migrations_archive_legacy_and_preserve_records(self):
        payload = {"outcomes": {"CG-00203": "delivered"},
                   "outcome_decisions": {"CG-00203": {"decision": "SHIP"}},
                   "messages": {"CG-00203": [{"text": "Yes", "source": "text"}]},
                   "training": {"model_id": "local-v1", "feedback": {"CG-00203": "delivered"}}}
        for kind in ("file", "sqlite"):
            with self.subTest(kind=kind):
                path = self.path.with_name(f"{kind}.json")
                path.write_text(json.dumps(payload if kind == "file" else {"obsolete": True}), encoding="utf-8")
                if kind == "sqlite":
                    with closing(sqlite3.connect(path.with_suffix(".sqlite3"))) as raw, raw:
                        raw.execute("CREATE TABLE app_state (id INTEGER PRIMARY KEY, payload TEXT)")
                        raw.execute("INSERT INTO app_state VALUES (1, ?)", (json.dumps(payload),))
                state = read_state(path)
                self.assertEqual(state["outcomes"], {"CG-00203": "delivered"})
                self.assertEqual(state["outcome_decisions"]["CG-00203"]["decision"], "SHIP")
                self.assertEqual(state["messages"]["CG-00203"][0]["text"], "Yes")
                self.assertFalse(path.exists())
                self.assertTrue(path.with_name(path.name + ".archive").exists())
                self.assertEqual(read_state(path), state)
                with connect(path) as db:
                    self.assertEqual(db.execute("SELECT model_id FROM model_versions").fetchone()[0], "local-v1")
                    self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='app_state'").fetchone())

    def test_malformed_legacy_json_remains_recoverable(self):
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(StateUnavailable):
            read_state(self.path)
        self.assertTrue(self.path.exists())
        self.path.write_text("{}", encoding="utf-8")
        self.assertEqual(read_state(self.path)["outcomes"], {})

    def test_migrate_normalized_database_backfills_reply_review_flag(self):
        with closing(sqlite3.connect(self.path.with_suffix(".sqlite3"))) as raw, raw:
            raw.execute("PRAGMA user_version=1")
            raw.execute("CREATE TABLE decisions (intent, why, default_snapshot)")
            raw.executemany("INSERT INTO decisions VALUES (?, ?, ?)",
                            [("CONFIRM", "Reply unclear; previous answer kept", 0),
                             ("UNCLEAR", "Please clarify", 0), ("CONFIRM", "Explicit answer", 0)])
        with connect(self.path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 10)
            self.assertEqual([row[0] for row in db.execute("SELECT needs_review FROM decisions ORDER BY rowid")],
                             [1, 1, 0])

    def test_migrate_v8_distinguishes_possible_historical_button_taps(self):
        with connect(self.path) as db, db:
            db.execute("DROP TABLE reply_corrections")
            db.execute("DROP TABLE reply_shadow_predictions")
            db.execute("PRAGMA user_version=8")
            db.executemany("""INSERT INTO messages (tenant_id,order_id,text,source,intent,actor)
                VALUES ('alpha','ORD-1',?,'whatsapp',?,'webhook')""",
                           [("Confirm", "CONFIRM"), ("Cancel", "DENY"), ("Yes", "CONFIRM")])
        with connect(self.path) as db:
            sources = [row["source"] for row in db.execute("SELECT source FROM messages ORDER BY id")]
            self.assertEqual(sources, ["whatsapp_legacy", "whatsapp_legacy", "whatsapp"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reply_corrections").fetchone()[0], 0)

    def test_migrate_v9_preserves_labels_and_adds_shadow_predictions(self):
        with connect(self.path) as db, db:
            db.execute("DROP TABLE reply_shadow_predictions")
            db.execute("PRAGMA user_version=9")
            db.execute("""INSERT INTO messages (id,tenant_id,order_id,text,source,intent,actor)
                VALUES (1,'alpha','ORD-1','Maybe','text','UNCLEAR','operator')""")
            db.execute("""INSERT INTO reply_corrections
                (tenant_id,message_id,label,language,decision_revision,at,actor)
                VALUES ('alpha',1,'DENY','en',2,'2026-11-20','operator')""")
        with connect(self.path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 10)
            self.assertEqual(db.execute("SELECT label FROM reply_corrections").fetchone()[0], "DENY")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reply_shadow_predictions").fetchone()[0], 0)

    def test_distinct_events_survive_eight_writers_and_failed_transaction(self):
        def append_batch(worker):
            for index in range(10):
                order_id = f"{worker}-{index}"
                with transaction(self.path, order_ids=(order_id,)) as state:
                    append_event(state, order_id, "outcome", f"worker-{worker}", outcome="refused")

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append_batch, range(8)))
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction(self.path) as state:
                append_event(state, "failed", "outcome", "operator", outcome="delivered")
                raise RuntimeError("rollback")
        state = read_state(self.path)
        self.assertEqual(len(state["events"]), 80)
        self.assertNotIn("failed", state["events"])

    def test_backup_restores_order_outcome_and_audit_counts(self):
        ensure_seeded(self.path, ROOT / "data/demo_orders.csv")
        with transaction(self.path, order_ids=("CG-00203",)) as state:
            append_event(state, "CG-00203", "outcome", "operator", outcome="refused")
        restored_directory = self.path.parent / "restored"
        restored_directory.mkdir()
        restored = restored_directory / "state.json"
        snapshot(self.path.with_suffix(".sqlite3"), restored.with_suffix(".sqlite3"))
        with connect(restored) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM orders").fetchone()[0], 80)
            self.assertEqual(db.execute("SELECT count(*) FROM outcomes").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM audit_events").fetchone()[0], 1)
        self.assertEqual(read_state(restored), read_state(self.path))
