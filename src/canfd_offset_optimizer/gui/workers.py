"""QObject worker for backend calls with explicit lifecycle signals."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from .contracts import (
    BackendError,
    CancellationToken,
    OptimizationCancelled,
    ProgressCallback,
    ProgressUpdate,
)


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    """Safe summary plus expandable technical detail."""

    user_message: str
    technical_details: str


BackendOperation = Callable[[ProgressCallback, CancellationToken], object]


class BackendWorker(QObject):
    """Run exactly one synchronous backend operation in a QThread."""

    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, operation: BackendOperation, token: CancellationToken) -> None:
        super().__init__()
        self._operation = operation
        self._token = token

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation(self._emit_progress, self._token)
        except OptimizationCancelled:
            self.cancelled.emit()
        except BackendError as exc:
            self.failed.emit(WorkerFailure(str(exc), traceback.format_exc()))
        except Exception as exc:  # GUI boundary must preserve unexpected technical details.
            self.failed.emit(
                WorkerFailure(
                    "后台任务发生意外错误，请展开技术详情。",
                    f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
                )
            )
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()

    def _emit_progress(self, update: ProgressUpdate) -> None:
        self.progress.emit(update)
