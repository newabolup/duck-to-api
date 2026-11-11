import asyncio
import json
import logging
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.adapters.base import (
    AdapterExecutionError,
    AdapterManualAuthRequired,
    EditRequest,
    GenerationRequest,
)
from app.adapters.registry import AdapterRegistry
from app.core.browser import BrowserManager
from app.core.security import sign_file_token
from app.core.storage import ImageStorage

logger = logging.getLogger("duck_to_api.jobs")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class JobRecord:
    id: str
    job_type: str
    adapter: str
    model: str | None
    prompt: str
    size: str | None
    n: int
    status: str
    input_filename: str | None
    output_filenames: list[str]
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    metadata: dict[str, Any]

    def to_dict(self, api_key: str | None = None) -> dict[str, Any]:
        input_url: str | None = None
        if self.input_filename:
            base = f"/files/uploads/{self.input_filename}"
            if api_key:
                tok = sign_file_token(api_key, f"uploads/{self.input_filename}")
                input_url = f"{base}?token={tok}"
            else:
                input_url = base

        output_urls: list[str] = []
        for name in self.output_filenames:
            base = f"/files/outputs/{name}"
            if api_key:
                tok = sign_file_token(api_key, f"outputs/{name}")
                output_urls.append(f"{base}?token={tok}")
            else:
                output_urls.append(base)

        return {
            "id": self.id,
            "job_type": self.job_type,
            "adapter": self.adapter,
            "model": self.model,
            "prompt": self.prompt,
            "size": self.size,
            "n": self.n,
            "status": self.status,
            "input_filename": self.input_filename,
            "input_url": input_url,
            "output_filenames": self.output_filenames,
            "output_urls": output_urls,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class JobStore:
    """SQLite persistence layer for queued, active, and historical jobs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    model TEXT,
                    prompt TEXT NOT NULL,
                    size TEXT,
                    n INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    input_filename TEXT,
                    output_filenames TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            job_type=row["job_type"],
            adapter=row["adapter"],
            model=row["model"],
            prompt=row["prompt"],
            size=row["size"],
            n=row["n"],
            status=row["status"],
            input_filename=row["input_filename"],
            output_filenames=json.loads(row["output_filenames"] or "[]"),
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            duration_ms=row["duration_ms"],
            metadata=json.loads(row["metadata"] or "{}"),
        )

    async def insert(self, job: JobRecord) -> None:
        async with self._lock:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        id, job_type, adapter, model, prompt, size, n, status,
                        input_filename, output_filenames, error, created_at,
                        started_at, finished_at, duration_ms, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.id,
                        job.job_type,
                        job.adapter,
                        job.model,
                        job.prompt,
                        job.size,
                        job.n,
                        job.status,
                        job.input_filename,
                        json.dumps(job.output_filenames),
                        job.error,
                        job.created_at,
                        job.started_at,
                        job.finished_at,
                        job.duration_ms,
                        json.dumps(job.metadata),
                    ),
                )

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._lock:
            with closing(self._connect()) as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                return self._row_to_record(row) if row else None

    async def list(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[JobRecord]:
        async with self._lock:
            with closing(self._connect()) as conn:
                if status and status != "all":
                    rows = conn.execute(
                        "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                        (status, limit, offset),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    ).fetchall()
                return [self._row_to_record(r) for r in rows]

    async def counts_by_status(self) -> dict[str, int]:
        async with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
                ).fetchall()
                counts = {
                    "queued": 0,
                    "running": 0,
                    "completed": 0,
                    "failed": 0,
                    "cancelled": 0,
                    "needs_auth": 0,
                }
                for row in rows:
                    counts[row["status"]] = row["cnt"]
                counts["total"] = sum(counts.values())
                return counts

    async def update(self, job_id: str, **fields: Any) -> JobRecord | None:
        if not fields:
            return await self.get(job_id)
        serialized: dict[str, Any] = {}
        for k, v in fields.items():
            if k in ("output_filenames", "metadata"):
                serialized[k] = json.dumps(v)
            else:
                serialized[k] = v
        assignments = ", ".join(f"{k} = ?" for k in serialized)
        values = list(serialized.values()) + [job_id]
        async with self._lock:
            with closing(self._connect()) as conn, conn:
                conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                return self._row_to_record(row) if row else None

    async def recover_interrupted(self) -> tuple[int, list[str]]:
        """Mark leftover running jobs as failed and return queued job IDs to resume."""
        async with self._lock:
            with closing(self._connect()) as conn, conn:
                cur = conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed',
                        error = 'Interrupted by server shutdown or restart',
                        finished_at = ?
                    WHERE status = 'running'
                    """,
                    (_utc_now(),),
                )
                recovered_count = cur.rowcount or 0
                rows = conn.execute(
                    "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at ASC"
                ).fetchall()
                return recovered_count, [row["id"] for row in rows]


class JobManager:
    """Async job queue, worker pool, concurrency control, and completion futures."""

    def __init__(
        self,
        store: JobStore,
        browser: BrowserManager,
        registry: AdapterRegistry,
        storage: ImageStorage,
        max_concurrent_jobs: int = 1,
        job_timeout_seconds: int = 180,
        sync_wait_timeout_seconds: int = 300,
    ) -> None:
        self.store = store
        self.browser = browser
        self.registry = registry
        self.storage = storage
        self.max_concurrent_jobs = max(1, max_concurrent_jobs)
        self.job_timeout_seconds = max(15, job_timeout_seconds)
        self.sync_wait_timeout_seconds = max(self.job_timeout_seconds + 15, sync_wait_timeout_seconds)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._waiters: dict[str, list[asyncio.Future[JobRecord]]] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        recovered_count, queued_ids = await self.store.recover_interrupted()
        for job_id in queued_ids:
            await self._queue.put(job_id)
        for idx in range(self.max_concurrent_jobs):
            task = asyncio.create_task(self._worker_loop(idx), name=f"job-worker-{idx}")
            self._workers.append(task)
        logger.info(
            "JobManager started with %d worker(s); recovered %d interrupted job(s), resumed %d queued job(s)",
            len(self._workers),
            recovered_count,
            len(queued_ids),
        )

    async def stop(self) -> None:
        self._started = False
        running = list(self._running_tasks.values())
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        for waiters in self._waiters.values():
            for fut in waiters:
                if not fut.done():
                    fut.cancel()
        self._waiters.clear()

    async def enqueue_generate(
        self,
        prompt: str,
        adapter_or_model: str | None = None,
        size: str | None = None,
        n: int = 1,
        options: dict[str, Any] | None = None,
    ) -> JobRecord:
        adapter = self.registry.get(adapter_or_model)
        if not adapter.capabilities.text_to_image:
            raise ValueError(f"Adapter '{adapter.name}' does not support text-to-image generation")
        job = JobRecord(
            id=f"job_{uuid.uuid4().hex[:12]}",
            job_type="generate",
            adapter=adapter.name,
            model=adapter_or_model or adapter.name,
            prompt=prompt.strip(),
            size=size,
            n=max(1, min(n, adapter.capabilities.max_images)),
            status="queued",
            input_filename=None,
            output_filenames=[],
            error=None,
            created_at=_utc_now(),
            started_at=None,
            finished_at=None,
            duration_ms=None,
            metadata={"options": options or {}},
        )
        await self.store.insert(job)
        await self._queue.put(job.id)
        logger.info("Queued generate job %s (adapter=%s)", job.id, job.adapter, extra={"job_id": job.id})
        return job

    async def enqueue_edit(
        self,
        prompt: str,
        image_bytes: bytes,
        adapter_or_model: str | None = None,
        size: str | None = None,
        n: int = 1,
        options: dict[str, Any] | None = None,
    ) -> JobRecord:
        adapter = self.registry.get(adapter_or_model)
        if not adapter.capabilities.image_edit:
            raise ValueError(f"Adapter '{adapter.name}' does not support image editing")
        stored_input = self.storage.save_upload(image_bytes, prefix="edit")
        job = JobRecord(
            id=f"job_{uuid.uuid4().hex[:12]}",
            job_type="edit",
            adapter=adapter.name,
            model=adapter_or_model or adapter.name,
            prompt=prompt.strip(),
            size=size,
            n=max(1, min(n, adapter.capabilities.max_images)),
            status="queued",
            input_filename=stored_input.filename,
            output_filenames=[],
            error=None,
            created_at=_utc_now(),
            started_at=None,
            finished_at=None,
            duration_ms=None,
            metadata={
                "options": options or {},
                "input_dimensions": f"{stored_input.width}x{stored_input.height}",
            },
        )
        await self.store.insert(job)
        await self._queue.put(job.id)
        logger.info(
            "Queued edit job %s (adapter=%s, input=%s)",
            job.id,
            job.adapter,
            stored_input.filename,
            extra={"job_id": job.id},
        )
        return job

    async def wait_for_job(self, job_id: str, timeout: float | None = None) -> JobRecord:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[JobRecord] = loop.create_future()
        self._waiters.setdefault(job_id, []).append(fut)
        try:
            current = await self.store.get(job_id)
            if current is None:
                raise KeyError(f"Job '{job_id}' not found")
            if current.status in ("completed", "failed", "cancelled", "needs_auth"):
                return current
            effective_timeout = timeout if timeout is not None else float(self.sync_wait_timeout_seconds)
            return await asyncio.wait_for(fut, timeout=effective_timeout)
        finally:
            waiter_list = self._waiters.get(job_id)
            if waiter_list and fut in waiter_list:
                waiter_list.remove(fut)

    def _notify_waiters(self, job: JobRecord) -> None:
        waiters = self._waiters.pop(job.id, [])
        for fut in waiters:
            if not fut.done():
                fut.set_result(job)

    async def cancel_job(self, job_id: str) -> JobRecord | None:
        job = await self.store.get(job_id)
        if not job:
            return None
        if job.status in ("completed", "failed", "cancelled"):
            return job
        running_task = self._running_tasks.get(job_id)
        if running_task and not running_task.done():
            running_task.cancel()
        updated = await self.store.update(
            job_id,
            status="cancelled",
            error="Cancelled by user",
            finished_at=_utc_now(),
        )
        if updated:
            logger.info("Cancelled job %s", job_id, extra={"job_id": job_id})
            self._notify_waiters(updated)
        return updated

    async def retry_job(self, job_id: str) -> JobRecord | None:
        job = await self.store.get(job_id)
        if not job:
            return None
        if job.status in ("queued", "running"):
            raise RuntimeError("Job is already queued or running")
        new_job = JobRecord(
            id=f"job_{uuid.uuid4().hex[:12]}",
            job_type=job.job_type,
            adapter=job.adapter,
            model=job.model,
            prompt=job.prompt,
            size=job.size,
            n=job.n,
            status="queued",
            input_filename=job.input_filename,
            output_filenames=[],
            error=None,
            created_at=_utc_now(),
            started_at=None,
            finished_at=None,
            duration_ms=None,
            metadata={**job.metadata, "retried_from": job.id},
        )
        await self.store.insert(new_job)
        await self._queue.put(new_job.id)
        logger.info("Retried job %s as %s", job.id, new_job.id, extra={"job_id": new_job.id})
        return new_job

    async def queue_snapshot(self) -> dict[str, Any]:
        counts = await self.store.counts_by_status()
        counts["queue_depth"] = self._queue.qsize()
        counts["active_workers"] = len(self._running_tasks)
        counts["max_concurrent_jobs"] = self.max_concurrent_jobs
        return counts

    async def _worker_loop(self, worker_idx: int) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                job = await self.store.get(job_id)
                if not job or job.status != "queued":
                    continue
                task = asyncio.create_task(self._execute_job(job), name=f"exec-{job_id}")
                self._running_tasks[job_id] = task
                try:
                    await task
                finally:
                    self._running_tasks.pop(job_id, None)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error in worker %d for job %s", worker_idx, job_id)
            finally:
                self._queue.task_done()

    async def _execute_job(self, job: JobRecord) -> None:
        start_mono = time.monotonic()
        await self.store.update(job.id, status="running", started_at=_utc_now(), error=None)
        logger.info("Started %s job %s on adapter '%s'", job.job_type, job.id, job.adapter, extra={"job_id": job.id})

        final_job: JobRecord | None = None
        try:
            adapter = self.registry.get(job.adapter)
            options = job.metadata.get("options", {})
            async with asyncio.timeout(self.job_timeout_seconds):
                async with self.browser.acquire_page() as page:
                    if job.job_type == "generate":
                        result = await adapter.generate_image(
                            page,
                            GenerationRequest(
                                prompt=job.prompt,
                                model=job.model,
                                size=job.size,
                                n=job.n,
                                options=options,
                            ),
                        )
                    elif job.job_type == "edit":
                        if not job.input_filename:
                            raise AdapterExecutionError("Missing input image filename for edit job")
                        input_path = self.storage.get_upload_path(job.input_filename)
                        result = await adapter.edit_image(
                            page,
                            EditRequest(
                                prompt=job.prompt,
                                image_path=input_path,
                                model=job.model,
                                size=job.size,
                                n=job.n,
                                options=options,
                            ),
                        )
                    else:
                        raise AdapterExecutionError(f"Unsupported job type: {job.job_type}")

            if not result.images_bytes:
                raise AdapterExecutionError("Adapter returned no image bytes")

            output_names: list[str] = []
            for idx, raw_bytes in enumerate(result.images_bytes):
                stored = self.storage.save_output(raw_bytes, job_id=job.id, index=idx)
                output_names.append(stored.filename)

            self.browser.clear_needs_auth(adapter.name)
            elapsed_ms = int((time.monotonic() - start_mono) * 1000)
            merged_meta = {**job.metadata, **result.metadata}
            if result.raw_text:
                merged_meta["raw_text"] = result.raw_text
            final_job = await self.store.update(
                job.id,
                status="completed",
                output_filenames=output_names,
                finished_at=_utc_now(),
                duration_ms=elapsed_ms,
                metadata=merged_meta,
            )
            logger.info(
                "Completed job %s in %d ms (%d output image(s))",
                job.id,
                elapsed_ms,
                len(output_names),
                extra={"job_id": job.id},
            )

        except asyncio.CancelledError:
            elapsed_ms = int((time.monotonic() - start_mono) * 1000)
            is_shutdown = not self._started
            final_job = await self.store.update(
                job.id,
                status="failed" if is_shutdown else "cancelled",
                error="Interrupted by server shutdown or restart" if is_shutdown else "Cancelled while running",
                finished_at=_utc_now(),
                duration_ms=elapsed_ms,
            )
            logger.warning("Job %s interrupted during execution (shutdown=%s)", job.id, is_shutdown, extra={"job_id": job.id})
        except AdapterManualAuthRequired as exc:
            elapsed_ms = int((time.monotonic() - start_mono) * 1000)
            self.browser.mark_needs_auth(job.adapter)
            final_job = await self.store.update(
                job.id,
                status="needs_auth",
                error=str(exc),
                finished_at=_utc_now(),
                duration_ms=elapsed_ms,
            )
            logger.warning("Job %s paused for manual auth: %s", job.id, exc, extra={"job_id": job.id})
        except TimeoutError:
            elapsed_ms = int((time.monotonic() - start_mono) * 1000)
            final_job = await self.store.update(
                job.id,
                status="failed",
                error=f"Timed out after {self.job_timeout_seconds}s",
                finished_at=_utc_now(),
                duration_ms=elapsed_ms,
            )
            logger.error("Job %s timed out after %ds", job.id, self.job_timeout_seconds, extra={"job_id": job.id})
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_mono) * 1000)
            final_job = await self.store.update(
                job.id,
                status="failed",
                error=str(exc),
                finished_at=_utc_now(),
                duration_ms=elapsed_ms,
            )
            logger.error("Job %s failed: %s", job.id, exc, extra={"job_id": job.id})
        finally:
            if final_job:
                self._notify_waiters(final_job)
