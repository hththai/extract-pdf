import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

JobStatus = Literal["queued", "processing", "done", "error"]

_TTL = 3600  # jobs expire after 1 hour


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = "queued"
    progress: int = 0
    total: int = 0
    result: pd.DataFrame | None = None
    filename: str = "classified.csv"
    error: str | None = None
    created_at: float = field(default_factory=time.time)


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def create(self, filename: str, total: int) -> Job:
        job = Job(filename=filename, total=total)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cleanup(self) -> None:
        cutoff = time.time() - _TTL
        stale = [jid for jid, j in self._jobs.items() if j.created_at < cutoff]
        for jid in stale:
            del self._jobs[jid]
