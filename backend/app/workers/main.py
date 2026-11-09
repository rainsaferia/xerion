"""Production background worker daemon entrypoint (PI-013, PI-053).

Worker claims queued jobs from Redis / Database queue, reads private file bytes from storage,
executes parsing, normalizes canonical objects, and updates progress and preview metadata.
Handles graceful shutdown on SIGINT / SIGTERM signals.
"""

import asyncio
import signal
import sys
from types import FrameType

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.queue.redis_queue import RedisQueueAdapter
from app.adapters.storage.local import LocalStorageAdapter
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import make_async_url
from app.workers.import_worker import process_next_job

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = structlog.get_logger()


class WorkerDaemon:
    def __init__(self) -> None:
        self.running = True
        self.settings = get_settings()

    def handle_signal(self, signum: int, frame: FrameType | None) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("worker.signal_received", signal=sig_name)
        self.running = False

    async def run(self) -> None:
        configure_logging(self.settings.log_level)
        logger.info(
            "worker.starting",
            database_url=self.settings.database_url.split("@")[-1],
            redis_url=self.settings.redis_url.split("@")[-1],
            storage_dir=self.settings.storage_local_dir,
        )

        engine = create_async_engine(
            make_async_url(self.settings.database_url),
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        storage = LocalStorageAdapter(self.settings.storage_local_dir)
        queue = RedisQueueAdapter(self.settings.redis_url)

        # Register signals for graceful shutdown (Unix only, fallback on Windows)
        loop = asyncio.get_running_loop()

        def _make_handler(s: signal.Signals) -> None:
            self.handle_signal(s.value, None)

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _make_handler, sig)
            except (NotImplementedError, RuntimeError):
                signal.signal(sig, self.handle_signal)

        logger.info("worker.ready_for_jobs")

        consecutive_idle = 0
        while self.running:
            try:
                async with session_factory() as session:
                    processed = await process_next_job(
                        session=session,
                        storage=storage,
                        queue=queue,
                        timeout_seconds=2.0,
                    )
                    if processed:
                        consecutive_idle = 0
                    else:
                        consecutive_idle += 1
                        # Back off slightly when idle
                        await asyncio.sleep(min(1.0, 0.1 * consecutive_idle))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("worker.loop_error", error=str(exc), exc_info=True)
                await asyncio.sleep(2.0)

        logger.info("worker.shutting_down")
        await engine.dispose()
        logger.info("worker.stopped_cleanly")


def main() -> None:
    daemon = WorkerDaemon()
    try:
        asyncio.run(daemon.run())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
