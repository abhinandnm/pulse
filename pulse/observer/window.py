import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from pulse.domain.transaction import TransactionResult


class SlidingWindow:
    """
    Time-bounded sliding window of transaction results.
    Maintains events strictly within the last `window_seconds`.
    """

    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self._queue: deque[Tuple[datetime, TransactionResult]] = deque()
        self._lock = threading.Lock()

    def add(self, result: TransactionResult, timestamp: Optional[datetime] = None) -> None:
        """Add a transaction result with its occurrence timestamp."""
        ts = timestamp or result.transaction.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        with self._lock:
            self._queue.append((ts, result))
            self._prune_locked(current_time=ts)

    def prune(self, current_time: Optional[datetime] = None) -> None:
        """Discard transactions that have aged past the window horizon."""
        with self._lock:
            self._prune_locked(current_time=current_time)

    def _prune_locked(self, current_time: Optional[datetime] = None) -> None:
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        cutoff = now - timedelta(seconds=self.window_seconds)
        while self._queue and self._queue[0][0] < cutoff:
            self._queue.popleft()

    def get_results(self) -> List[TransactionResult]:
        """Return all transaction results currently in the sliding window."""
        with self._lock:
            self._prune_locked()
            return [item[1] for item in self._queue]

    def count(self) -> int:
        """Number of active transactions in the window."""
        with self._lock:
            self._prune_locked()
            return len(self._queue)

    def clear(self) -> None:
        """Empty the sliding window."""
        with self._lock:
            self._queue.clear()
