"""Publish immutable model artifacts through one atomic pointer."""
import json
import os
import pickle
import re
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def active_version(model_path):
    model_path = Path(model_path)
    try:
        name = model_path.with_suffix(".active").read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    if not re.fullmatch(r"[0-9a-f]{32}", name):
        raise ValueError("Invalid active version pointer")
    return model_path.with_suffix(".versions") / name


def publish(bundle, evaluation, report, model_path, *, expected):
    if bundle["model_id"] != evaluation["model_id"]:
        raise ValueError("Cannot publish mismatched model and evaluation")
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    # This lock coordinates publishers across API and dashboard processes. Serving
    # never opens it, and no order-state lock is held while artifacts are written.
    lock = sqlite3.connect(model_path.with_suffix(".publish.sqlite3"))
    try:
        lock.execute("BEGIN IMMEDIATE")
        if active_version(model_path) != expected:
            raise ValueError("The active model changed during training. Retrain from the latest version.")
        version = model_path.with_suffix(".versions") / uuid4().hex
        version.mkdir(parents=True)
        files = (version / "model.pkl", version / "evaluation.json", version / "report.md")
        try:
            atomic_write(files[0], pickle.dumps(bundle))
            atomic_write(files[1], json.dumps(evaluation, indent=2).encode("utf-8"))
            atomic_write(files[2], report.encode("utf-8"))
            atomic_write(model_path.with_suffix(".active"), version.name.encode("ascii"))
        except BaseException:
            for path in files:
                path.unlink(missing_ok=True)
            version.rmdir()
            raise
    finally:
        lock.close()
