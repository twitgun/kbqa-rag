"""单 worker 后台任务：GPU 推理本就串行，多 worker 无收益（ADR-013）。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from kbqa.infra.db import session as dbsession
from kbqa.infra.db.repositories import JobRepo

logger = logging.getLogger("kbqa.jobs")


class JobContext:
    def __init__(self, job_id: int) -> None:
        self.job_id = job_id

    def set_progress(self, done: int, total: int, message: str) -> None:
        with dbsession.SessionLocal() as db:
            JobRepo(db).set_progress(self.job_id, done, total, message)
            db.commit()


class JobRunner:
    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix="kbqa-job")

    def submit(self, *, job_type: str, doc_id: int | None,
               fn: Callable[[JobContext], None]) -> int:
        with dbsession.SessionLocal() as db:
            job = JobRepo(db).create(job_type=job_type, doc_id=doc_id)
            job_id = job.id
            db.commit()
        self._executor.submit(self._run, job_id, fn)
        return job_id

    def _run(self, job_id: int, fn: Callable[[JobContext], None]) -> None:
        with dbsession.SessionLocal() as db:
            JobRepo(db).mark_running(job_id)
            db.commit()
        try:
            fn(JobContext(job_id))
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_failed job_id=%s", job_id)
            with dbsession.SessionLocal() as db:
                JobRepo(db).finish(job_id, "failed",
                                   error_code=getattr(exc, "code", "E-2004"),
                                   error_detail=f"{type(exc).__name__}: {exc}")
                db.commit()
            return
        with dbsession.SessionLocal() as db:
            JobRepo(db).finish(job_id, "succeeded")
            db.commit()

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
