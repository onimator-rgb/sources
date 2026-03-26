"""
Generic background worker for long-running operations.

Usage:
    worker = WorkerThread(fn, arg1, arg2, kwarg=value)
    worker.result.connect(on_result)
    worker.error.connect(on_error)
    worker.start()
"""
import logging
from typing import Callable, Any

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class WorkerThread(QThread):
    result = Signal(object)
    error = Signal(str)

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.result.emit(result)
        except Exception as e:
            logger.exception(f"Worker error in {self._fn.__name__}: {e}")
            self.error.emit(str(e))
