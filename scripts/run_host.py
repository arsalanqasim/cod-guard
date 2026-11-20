"""Bootstrap the loopback API and isolated dashboard from one checkout."""
import argparse
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
import venv

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def bootstrap():
    folder = ROOT / ".venv/host"
    python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(folder)
    requirements = ROOT / "requirements.txt"
    stamp = folder / "requirements.sha256"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not stamp.is_file() or stamp.read_text(encoding="ascii") != digest:
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                        "-r", str(requirements)], check=True)
        stamp.write_text(digest, encoding="ascii")
    return str(python)


def ensure_baseline(model_path):
    sys.path.insert(0, str(ROOT / "backend/app"))
    import pandas as pd
    from artifacts import active_version, publish
    from train_model import fit_and_evaluate, render_report

    if active_version(model_path) is not None:
        return
    bundle, report = fit_and_evaluate(pd.read_csv(ROOT / "data/benchmark_orders.csv"))
    publish(bundle, report, render_report(report), model_path, expected=None)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_http(url, processes, status=200):
    deadline = monotonic() + 45
    opener = build_opener(ProxyHandler({}))
    while monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("A hosted process exited before startup completed")
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == status:
                    return
        except HTTPError as exc:
            if exc.code == status:
                return
        except (OSError, URLError):
            pass
        sleep(.25)
    raise RuntimeError(f"Expected HTTP {status} at {url}")


def run(args):
    if any(not 1 <= port <= 65535 for port in (args.api_port, args.dashboard_port)):
        raise ValueError("Ports must be between 1 and 65535")
    if args.api_port == args.dashboard_port:
        raise ValueError("Choose distinct ports for the API and dashboard")
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_demo import demo_session

    with ExitStack() as stack:
        data = (Path(stack.enter_context(TemporaryDirectory(prefix="cod-guard-host-smoke-")))
                if args.smoke else args.data_dir.resolve())
        model_path = data / "model.pkl"
        demo_model_path = data / "exhibition" / "model.pkl"
        ensure_baseline(model_path)
        ensure_baseline(demo_model_path)
        env = {**os.environ, "COD_GUARD_DATA_DIR": str(data), "COD_GUARD_MODEL_PATH": str(model_path),
               "COD_GUARD_OFFLINE": "1", "HF_HUB_OFFLINE": "1"}
        dashboard_env = stack.enter_context(demo_session(demo_model_path))
        definitions = [("uvicorn", ["backend.app.main:app", "--host", "127.0.0.1", "--port",
                                    str(args.api_port), "--no-access-log"], env),
                       ("streamlit", ["run", "frontend/dashboard.py", "--server.address", "127.0.0.1",
                                      "--server.port", str(args.dashboard_port), "--server.headless", "true"],
                        dashboard_env)]
        processes = []
        for module, flags, child_env in definitions:
            process = subprocess.Popen([PYTHON, "-m", module, *flags], cwd=ROOT, env=child_env)
            stack.callback(stop, process)
            processes.append(process)
        api = f"http://127.0.0.1:{args.api_port}"
        dashboard = f"http://127.0.0.1:{args.dashboard_port}"
        wait_http(api + "/ready", processes)
        wait_http(api + "/orders", processes, status=401)
        wait_http(dashboard + "/_stcore/health", processes)
        print(f"API ready at {api} and dashboard ready at {dashboard}", flush=True)
        if args.smoke:
            return
        while all(process.poll() is None for process in processes):
            sleep(.5)
        raise RuntimeError("A hosted process exited")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Start, verify and stop both processes on disposable state")
    parser.add_argument("--data-dir", type=Path,
                        default=Path(os.environ.get("COD_GUARD_DATA_DIR", ROOT / "host-data")))
    parser.add_argument("--api-port", type=int, default=8000, metavar="PORT")
    parser.add_argument("--dashboard-port", type=int, default=8501, metavar="PORT")
    args = parser.parse_args()
    if args.bootstrap:
        python = bootstrap()
        return subprocess.call([python, __file__, *(arg for arg in sys.argv[1:] if arg != "--bootstrap")], cwd=ROOT)
    try:
        run(args)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Host setup: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
