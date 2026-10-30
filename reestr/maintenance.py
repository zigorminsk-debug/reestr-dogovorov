from __future__ import annotations

import threading
from contextlib import contextmanager


class MaintenanceBlocked(RuntimeError):
    """Raised when another maintenance operation is already running."""


class DatabaseGate:
    """Pause new DB work and wait for active requests before restoring a file."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = 0
        self._maintenance = False

    @property
    def is_maintenance(self) -> bool:
        with self._condition:
            return self._maintenance

    def enter(self) -> bool:
        with self._condition:
            if self._maintenance:
                return False
            self._active += 1
            return True

    def exit(self) -> None:
        with self._condition:
            if self._active > 0:
                self._active -= 1
            if self._active == 0:
                self._condition.notify_all()

    @contextmanager
    def background(self):
        if not self.enter():
            raise MaintenanceBlocked("Выполняется восстановление базы")
        try:
            yield
        finally:
            self.exit()

    @contextmanager
    def maintenance(self, timeout: float = 60):
        with self._condition:
            if self._maintenance:
                raise MaintenanceBlocked("Другое восстановление уже выполняется")
            self._maintenance = True
            finished = self._condition.wait_for(lambda: self._active == 0, timeout=timeout)
            if not finished:
                self._maintenance = False
                self._condition.notify_all()
                raise MaintenanceBlocked(
                    "Не удалось дождаться завершения активных запросов. Повторите попытку."
                )
        try:
            yield
        finally:
            with self._condition:
                self._maintenance = False
                self._condition.notify_all()
