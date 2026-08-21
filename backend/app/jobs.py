from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        # SQLite e os scrapers trabalham melhor serializados nesta aplicação.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tradefot-job")

    def submit(self, kind: str, task: Callable[[Callable], dict]) -> dict:
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "progress": 0,
            "current": 0,
            "total": 0,
            "message": "Aguardando execução",
            "result": None,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock:
            self._jobs[job_id] = job

        def progress(current: int, total: int, message: str) -> None:
            with self._lock:
                target = self._jobs[job_id]
                target.update(
                    {
                        "current": int(current),
                        "total": int(total),
                        "progress": round(current / total * 100, 1) if total else 0,
                        "message": str(message),
                        "updated_at": _now(),
                    }
                )

        def run() -> None:
            with self._lock:
                self._jobs[job_id].update(
                    {"status": "running", "message": "Iniciando", "updated_at": _now()}
                )
            try:
                result = task(progress)
                with self._lock:
                    self._jobs[job_id].update(
                        {
                            "status": "completed",
                            "progress": 100,
                            "result": result,
                            "message": "Concluído",
                            "updated_at": _now(),
                        }
                    )
            except Exception as exc:
                with self._lock:
                    self._jobs[job_id].update(
                        {
                            "status": "failed",
                            "error": str(exc),
                            "message": "Falha na execução",
                            "updated_at": _now(),
                        }
                    )

        self._executor.submit(run)
        return self.get(job_id)

    def get(self, job_id: str) -> dict:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return dict(self._jobs[job_id])

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)


jobs = JobManager()
