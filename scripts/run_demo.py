"""Start an offline dashboard with fresh disposable orders and model state."""
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
from artifacts import active_version


@contextmanager
def demo_session(model_path=ROOT / "backend/app/model.pkl"):
    baseline = active_version(model_path)
    if baseline is None:
        raise ValueError("Run python scripts/build_demo.py to provision the synthetic baseline")
    report = json.loads((baseline / "evaluation.json").read_text(encoding="utf-8"))
    if report["split"]["feedback"]:
        raise ValueError("Rebuild the synthetic baseline with python scripts/build_demo.py")
    with TemporaryDirectory(prefix="cod-guard-demo-") as session:
        folder = Path(session)
        shutil.copytree(baseline, folder / "model.versions" / baseline.name)
        (folder / "model.active").write_text(baseline.name, encoding="ascii")
        yield {**os.environ, "COD_GUARD_MODEL_PATH": str(folder / "model.pkl"),
               "COD_GUARD_DATA_DIR": str(folder), "COD_GUARD_OFFLINE": "1", "HF_HUB_OFFLINE": "1",
               "COD_GUARD_EXHIBITION": "1", "COD_GUARD_WOO_HEALTH_LOCAL": "0",
               "COD_GUARD_WHATSAPP": "{}", "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false"}


def main():
    try:
        with demo_session() as env:
            return subprocess.call([sys.executable, "-m", "streamlit", "run", "frontend/dashboard.py",
                                    "--server.address", "127.0.0.1"], env=env, cwd=ROOT)
    except (OSError, ValueError) as exc:
        print(f"Demo setup: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
