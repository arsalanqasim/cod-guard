"""Remove expired raw reply bodies while retaining decisions and audit events."""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from records import audit, write
from platform_data import database_url


def purge(path, days, *, today=None, tenant_id=None):
    if days < 1:
        raise ValueError("Retention must be at least one day")
    cutoff = (today or datetime.now(timezone.utc)) - timedelta(days=days)
    if database_url() and not tenant_id:
        raise ValueError("Specify a merchant tenant for PostgreSQL retention")
    with write(path, tenant_id=tenant_id) as db:
        if not getattr(db, "encrypted", False):
            db.execute("PRAGMA secure_delete=ON")
        raw_before = "text IS NOT NULL AND (at IS NULL OR at < ?)"
        expired = db.execute(f"SELECT DISTINCT tenant_id FROM messages WHERE {raw_before}",
                             (cutoff.isoformat(),)).fetchall()
        count = db.execute(f"UPDATE messages SET text=NULL WHERE {raw_before}", (cutoff.isoformat(),)).rowcount
        for tenant in expired:
            audit(db, tenant["tenant_id"], "retention-job", "purge_replies", reference=cutoff.isoformat())
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=os.environ.get("COD_GUARD_REPLY_RETENTION_DAYS", "30"))
    parser.add_argument("--state", type=Path,
                        default=Path(os.environ.get("COD_GUARD_DATA_DIR", ROOT / "data")) / "state.json")
    parser.add_argument("--tenant", help="Merchant tenant for PostgreSQL retention")
    args = parser.parse_args()
    print(f"Purged {purge(args.state, args.days, tenant_id=args.tenant)} raw reply bodies")
