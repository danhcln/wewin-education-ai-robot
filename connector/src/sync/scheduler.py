"""Single-owner scheduler at 08:00/20:00 Asia/Bangkok, with persisted catch-up."""
import asyncio
from datetime import datetime, timedelta, timezone
from src.config import settings
from src.utils.logger import logger
from src.sync.sync_engine import get_sync_engine, SyncAlreadyRunningError

BANGKOK = timezone(timedelta(hours=7))


def latest_slot(now=None):
    now = (now or datetime.now(BANGKOK)).astimezone(BANGKOK)
    morning = now.replace(hour=8, minute=0, second=0, microsecond=0)
    evening = morning.replace(hour=20)
    return evening if now >= evening else morning if now >= morning else evening - timedelta(days=1)


def next_slot(now=None):
    current = (now or datetime.now(BANGKOK)).astimezone(BANGKOK)
    last = latest_slot(current)
    return last + timedelta(hours=12)


class BackgroundSyncScheduler:
    def __init__(self, interval_hours=None):
        self._task = None
        self._stop_event = asyncio.Event()
        self._engine = None

    def start(self):
        if not (settings.SYNC_SCHEDULER_OWNER == "internal" and settings.SYNC_SCHEDULE_ARMED and settings.AUTO_SYNC_ENABLED):
            logger.info("Internal scheduler not armed or not the selected owner; no worker started.")
            return False
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop())
        return True

    async def tick(self, now=None):
        if not (settings.SYNC_SCHEDULER_OWNER == "internal" and settings.SYNC_SCHEDULE_ARMED and settings.AUTO_SYNC_ENABLED):
            return False
        engine = get_sync_engine()
        slot = latest_slot(now).isoformat()
        if engine.db.get_state("last_scheduled_slot", "") == slot:
            return False
        self._engine = engine
        try:
            report = await asyncio.to_thread(engine.run_sync, trigger_type="scheduled", scheduled_slot=slot, cancel_event=self._stop_event)
            if report.status in ("success", "partial", "failed") and report.pages_unprocessed == 0 and report.batch_target_count > 0:
                engine.db.set_state("last_scheduled_slot", slot)
            return True
        except SyncAlreadyRunningError:
            return False
        finally:
            self._engine = None

    async def _loop(self):
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                logger.error("Internal sync tick failed; saved checkpoint retained.")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        self._stop_event.set()
        if self._engine is not None and getattr(self._engine, "active_trigger", None) == "scheduled":
            self._engine.request_stop()
        if self._task and not self._task.done():
            # Never cancel a worker thread and prematurely release its job lock.
            await self._task


_scheduler_instance = None


def get_scheduler():
    global _scheduler_instance
    if _scheduler_instance is None: _scheduler_instance = BackgroundSyncScheduler()
    return _scheduler_instance
