"""Bounded background jobs within one application process."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4


class QueueFull(Exception):
    pass


class JobQueue:
    def __init__(self, *, workers, capacity):
        self._executor = ThreadPoolExecutor(max_workers=workers)
        self._capacity = capacity
        self._jobs = {}
        self._lock = Lock()

    def submit(self, work, *, scope=None):
        with self._lock:
            active = sum(job["status"] in ("queued", "running") for job, _ in self._jobs.values())
            if active >= self._capacity:
                raise QueueFull("The job queue is busy")
            if len(self._jobs) >= 128:
                oldest = next(key for key, (job, _) in self._jobs.items()
                              if job["status"] in ("done", "failed"))
                del self._jobs[oldest]
            job_id = uuid4().hex
            job = {"job_id": job_id, "status": "queued"}
            self._jobs[job_id] = (job, scope)
            self._executor.submit(self._run, job, work)
            return job.copy()

    def _run(self, job, work):
        with self._lock:
            job["status"] = "running"
        try:
            result = {"status": "done", "result": work()}
        except ValueError as exc:
            result = {"status": "failed", "error": str(exc)}
        except Exception:
            from logging import getLogger
            getLogger(__name__).exception("Background job %s failed", job["job_id"])
            result = {"status": "failed", "error": "Background job failed. See application logs."}
        with self._lock:
            job.update(result)

    def get(self, job_id, *, scope=None):
        with self._lock:
            job, owner = self._jobs[job_id]
            if owner != scope:
                raise KeyError(job_id)
            return job.copy()
