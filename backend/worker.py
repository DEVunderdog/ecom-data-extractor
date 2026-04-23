"""Async worker pool: consumes job IDs from a queue and runs the scraper."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from scraper import run_scrape

logger = logging.getLogger("worker")

MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "3"))


class WorkerPool:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Re-enqueue any jobs left in queued state from a prior run
        cursor = self.db.jobs.find({"status": "queued"}, {"_id": 0, "id": 1})
        async for doc in cursor:
            await self.queue.put(doc["id"])
        for i in range(MAX_CONCURRENT_JOBS):
            t = asyncio.create_task(self._consumer(i), name=f"scrape-worker-{i}")
            self._tasks.append(t)
        logger.info("Worker pool started (%d consumers)", MAX_CONCURRENT_JOBS)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("Worker pool stopped")

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)

    # ------------------------------------------------------------------
    async def _consumer(self, idx: int) -> None:
        logger.info("Consumer %d started", idx)
        while self._running:
            try:
                job_id = await self.queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._run_job(job_id)
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                logger.exception("Worker %d crashed on job %s: %s", idx, job_id, e)
            finally:
                self.queue.task_done()

    # ------------------------------------------------------------------
    async def _job_exists(self, job_id: str) -> bool:
        return (await self.db.jobs.count_documents({"id": job_id}, limit=1)) > 0

    async def _write_log(self, job_id: str, level: str, message: str, meta: Optional[dict]) -> None:
        doc = {
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "level": level,
            "message": message,
            "meta": meta or {},
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self.db.logs.insert_one(dict(doc))
        except Exception as e:  # noqa: BLE001
            logger.warning("Log insert failed: %s", e)

    async def _save_products(self, job_id: str, products: list[dict]) -> int:
        if not products:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        docs = []
        for p in products:
            docs.append(
                {
                    "id": str(uuid.uuid4()),
                    "job_id": job_id,
                    "data": p,
                    "scraped_at": p.get("scraped_at") or now,
                }
            )
        if not docs:
            return 0
        await self.db.products.insert_many(docs)
        await self.db.jobs.update_one(
            {"id": job_id}, {"$inc": {"products_count": len(docs)}}
        )
        return len(docs)

    # ------------------------------------------------------------------
    async def _run_job(self, job_id: str) -> None:
        job = await self.db.jobs.find_one({"id": job_id}, {"_id": 0})
        if not job:
            logger.info("Job %s vanished before start", job_id)
            return
        if job.get("status") not in ("queued", "running"):
            return

        url = job["url"]
        await self.db.jobs.update_one(
            {"id": job_id},
            {
                "$set": {
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "pages_scraped": 0,
                    "products_count": 0,
                    "error": None,
                }
            },
        )

        # closures to pass to the scraper
        async def log_fn(level: str, message: str, meta: Optional[dict]) -> None:
            await self._write_log(job_id, level, message, meta)

        async def save_fn(products: list[dict]) -> int:
            # update pages_scraped on each batch (scraper logs it too, but keep live metric)
            return await self._save_products(job_id, products)

        async def inc_pages_fn() -> None:
            await self.db.jobs.update_one({"id": job_id}, {"$inc": {"pages_scraped": 1}})

        async def cancel_fn() -> bool:
            return not await self._job_exists(job_id)

        try:
            result = await run_scrape(
                job_id=job_id, url=url, log=log_fn, save_products=save_fn,
                is_cancelled=cancel_fn, on_page=inc_pages_fn,
            )
            if not await self._job_exists(job_id):
                logger.info("Job %s cancelled during scrape", job_id)
                return
            await self.db.jobs.update_one(
                {"id": job_id},
                {
                    "$set": {
                        "status": "completed",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "pages_scraped": result["pages_scraped"],
                        # products_count already incremented live
                    }
                },
            )
            await self._write_log(
                job_id,
                "INFO",
                f"Job completed: {result['pages_scraped']} pages, {result['products_count']} products",
                result,
            )
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            logger.exception("Scrape failed for job %s", job_id)
            if await self._job_exists(job_id):
                await self.db.jobs.update_one(
                    {"id": job_id},
                    {
                        "$set": {
                            "status": "failed",
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "error": msg,
                        }
                    },
                )
                await self._write_log(job_id, "ERROR", f"Job failed: {msg}", None)
