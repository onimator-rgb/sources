"""
Generic background worker for long-running operations.

Usage:
    worker = WorkerThread(fn, arg1, arg2, kwarg=value)
    worker.result.connect(on_result)
    worker.error.connect(on_error)
    worker.start()

Cancellation (cooperative):
    worker.cancel()                  # request cancellation
    # Inside the worker function, check periodically:
    if worker.is_cancelled:
        return partial_result
"""
import logging
import threading
from typing import Callable, Any

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class WorkerThread(QThread):
    result = Signal(object)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._cancelled = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        """Check whether cancellation has been requested (thread-safe)."""
        return self._cancelled.is_set()

    def cancel(self) -> None:
        """Request cooperative cancellation of the running operation."""
        self._cancelled.set()
        logger.info("Cancellation requested for worker: %s", self._fn.__name__)

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            if self._cancelled.is_set():
                logger.info("Worker %s cancelled", self._fn.__name__)
                self.cancelled.emit()
                return
            self.result.emit(result)
        except Exception as e:
            if self._cancelled.is_set():
                logger.info("Worker %s cancelled (with exception)", self._fn.__name__)
                self.cancelled.emit()
                return
            logger.exception(f"Worker error in {self._fn.__name__}: {e}")
            self.error.emit(str(e))
