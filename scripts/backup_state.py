"""Snapshot COD-Guard's SQLite state using SQLite's online backup API."""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def snapshot(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    if source == destination.resolve():
        raise ValueError("Snapshot destination must differ from the source")
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as live, \
             closing(sqlite3.connect(destination)) as copy:
            live.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Snapshot failed SQLite integrity verification")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Active state.sqlite3")
    parser.add_argument("destination", type=Path, help="New snapshot path")
    args = parser.parse_args()
    snapshot(args.source, args.destination)
    print(f"Verified SQLite snapshot at {args.destination}")
