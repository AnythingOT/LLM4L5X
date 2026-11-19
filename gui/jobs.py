"""Long work in the background (a requirements workbook can take minutes on a CPU): the page
starts a job, then polls it for progress and the result."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    total: int
    done: int = 0
    status: str = "running"  # running | finished | failed | cancelled
    label: str = ""  # what it is working on now
    events: list[dict] = field(default_factory=list)  # results so far, in order
    result: dict | None = None
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def view(self, since: int = 0) -> dict:
        with self.lock:
            return {"id": self.id, "status": self.status, "done": self.done, "total": self.total,
                    "label": self.label, "events": self.events[since:], "next": len(self.events),
                    "result": self.result, "error": self.error}


JOBS: dict[str, Job] = {}


def start(total: int, work) -> Job:
    """Run work(job) in a thread. work reports through job.events / job.done and returns the result."""
    for old in [j for j in JOBS.values() if j.status != "running"]:
        JOBS.pop(old.id, None)  # keep only what the page may still poll
    job = Job(uuid.uuid4().hex[:12], total)
    JOBS[job.id] = job

    def run():
        try:
            result = work(job)
            with job.lock:
                job.result = result
                job.status = "cancelled" if job.cancel.is_set() else "finished"
        except Exception as e:  # noqa: BLE001 - reported to the page instead of killing the thread silently
            with job.lock:
                job.status, job.error = "failed", f"{type(e).__name__}: {e}"

    threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
    return job
