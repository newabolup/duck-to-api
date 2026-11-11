import asyncio
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import AsyncIterator


@dataclass(slots=True)
class LogEntry:
    id: int
    timestamp: str
    level: str
    logger: str
    message: str
    job_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class LogBus(logging.Handler):
    """In-memory ring buffer and SSE broadcaster for runtime logs."""

    def __init__(self, maxlen: int = 400) -> None:
        super().__init__()
        self._buffer: deque[LogEntry] = deque(maxlen=maxlen)
        self._subscribers: set[asyncio.Queue[LogEntry]] = set()
        self._seq = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        self._seq += 1
        entry = LogEntry(
            id=self._seq,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            level=record.levelname,
            logger=record.name,
            message=self.format(record) if self.formatter else record.getMessage(),
            job_id=getattr(record, "job_id", None),
        )
        self._buffer.append(entry)
        self._broadcast(entry)

    def _broadcast(self, entry: LogEntry) -> None:
        if not self._subscribers:
            return
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._push_to_queues, entry)
        else:
            self._push_to_queues(entry)

    def _push_to_queues(self, entry: LogEntry) -> None:
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def recent(self, limit: int = 200) -> list[dict]:
        items = list(self._buffer)[-limit:]
        return [item.to_dict() for item in items]

    async def subscribe(self) -> AsyncIterator[LogEntry]:
        queue: asyncio.Queue[LogEntry] = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        try:
            while True:
                entry = await queue.get()
                yield entry
        finally:
            self._subscribers.discard(queue)
