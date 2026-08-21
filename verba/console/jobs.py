"""Background jobs: long pipeline steps with a readable live log."""
from __future__ import annotations

import threading
import traceback
import uuid
from collections import deque
from datetime import datetime


class Job:
    def __init__(self, name: str, detail: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.detail = detail
        self.state = "running"          # running | done | failed
        self.started = datetime.now().isoformat(timespec="seconds")
        self.finished: str | None = None
        self.lines: deque[str] = deque(maxlen=800)
        self.result: dict = {}
        self.error: str = ""

    def log(self, text: str):
        for line in str(text).rstrip().splitlines() or [""]:
            self.lines.append(line)

    def to_dict(self, since: int = 0) -> dict:
        lines = list(self.lines)
        return {
            "id": self.id, "name": self.name, "detail": self.detail,
            "state": self.state, "started": self.started, "finished": self.finished,
            "lines": lines[since:], "total_lines": len(lines),
            "result": self.result, "error": self.error,
        }


class JobRunner:
    def __init__(self, incidents=None):
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.incidents = incidents

    def start(self, name: str, fn, detail: str = "") -> Job:
        job = Job(name, detail)
        with self._lock:
            self.jobs[job.id] = job

        def run():
            try:
                out = fn(job.log)
                job.result = out or {}
                job.state = "done"
            except Exception as e:
                # RuntimeError is what this codebase raises for conditions a
                # person can act on. A stack trace for "no password saved" buries
                # the sentence that matters.
                job.error = str(e) if isinstance(e, RuntimeError) \
                    else f"{type(e).__name__}: {e}"
                if not isinstance(e, RuntimeError):
                    job.log(traceback.format_exc())
                else:
                    job.log(job.error)
                job.state = "failed"
                if self.incidents is not None:
                    try:
                        self.incidents.record(
                            f"{name} ({detail})" if detail else name, e,
                            context={"job": job.id,
                                     "log": list(job.lines)[-14:]})
                    except Exception:
                        pass   # recording a fault must never cause one
            finally:
                job.finished = datetime.now().isoformat(timespec="seconds")

        threading.Thread(target=run, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def running(self) -> dict | None:
        """Whatever is running right now, for any window that asks.

        A crawl started in one view used to be visible only in that view: leave
        the page and the job carried on with nothing to show for it, so the
        honest answer to "is it still going?" was to start another one.
        """
        live = [j for j in self.jobs.values() if j.state == "running"]
        if not live:
            return None
        j = sorted(live, key=lambda x: x.started)[0]
        return {"id": j.id, "name": j.name, "detail": j.detail,
                "state": j.state, "started": j.started}

    def recent(self, limit: int = 12) -> list[dict]:
        js = sorted(self.jobs.values(), key=lambda j: j.started, reverse=True)
        return [{"id": j.id, "name": j.name, "detail": j.detail, "state": j.state,
                 "started": j.started, "finished": j.finished, "error": j.error}
                for j in js[:limit]]
