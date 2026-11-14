"""Background execution so USB transfers and parsing never block the GUI."""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from ..core.link import ERR_NOT_FOUND, DeviceInfo, HelperLink, Link, LinkError, MockLink

log = logging.getLogger(__name__)


class TaskError(str):
    """Error text passed to ``on_fail``; ``code`` is the LinkError code if any."""

    code: int | None = None


def _task_error(exc: Exception) -> TaskError:
    err = TaskError(str(exc))
    err.code = getattr(exc, "code", None)
    return err


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)  # TaskError
    progress = Signal(int, int)


class Task(QRunnable):
    """Runs ``fn(progress)`` in a pool; ``progress(done, total)`` is thread-safe."""

    def __init__(self, fn: Callable[[Callable[[int, int], None]], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn(self.signals.progress.emit)
        except Exception as exc:  # reported to the GUI, not swallowed
            if not isinstance(exc, (LinkError, OSError, ValueError)):
                log.error("tarea fallida\n%s", traceback.format_exc())
            self.signals.failed.emit(_task_error(exc))
        else:
            self.signals.done.emit(result)


_live_tasks: set[Task] = set()  # keeps Python wrappers (and their signals) alive until finished


def run_task(fn, on_done=None, on_fail=None, on_progress=None, pool: QThreadPool | None = None) -> Task:
    task = Task(fn)
    task.setAutoDelete(False)
    _live_tasks.add(task)
    task.signals.done.connect(lambda _r: _live_tasks.discard(task))
    task.signals.failed.connect(lambda _e: _live_tasks.discard(task))
    if on_done:
        task.signals.done.connect(on_done)
    if on_fail:
        task.signals.failed.connect(on_fail)
    if on_progress:
        task.signals.progress.connect(on_progress)
    (pool or QThreadPool.globalInstance()).start(task)
    return task


class LinkService(QObject):
    """Owns the calculator link; runs every USB operation on one worker thread.

    Signals:
      state(str): "disconnected" | "connecting" | "connected" | "busy"
      info(DeviceInfo)
      message(level, text)
    """

    state = Signal(str)
    info = Signal(object)
    message = Signal(str, str)

    def __init__(self, demo: bool = False, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)  # the calculator handles one request at a time
        self.demo = demo
        self.link: Link = self._make_link(demo)
        self.device: DeviceInfo | None = None
        self._state = "disconnected"
        self._pending = 0
        self.auto_connect = True
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._poll)

    @staticmethod
    def _make_link(demo: bool) -> Link:
        if demo:
            from ..core.demo import demo_link
            return demo_link()
        from ..config import log_dir
        return HelperLink(log_path=log_dir() / "tcm-link.log")

    @property
    def connected(self) -> bool:
        return self._state in ("connected", "busy")

    def start(self) -> None:
        self._timer.start()
        self._poll()

    def set_demo(self, demo: bool) -> None:
        if demo == self.demo:
            return
        self.disconnect_link()
        self.demo = demo
        self.link = self._make_link(demo)
        self._poll()

    def _set_state(self, s: str) -> None:
        if s != self._state:
            self._state = s
            self.state.emit(s)

    def _poll(self) -> None:
        """Auto-detection: probe USB (cheap, no link opened) and connect when found."""
        if self._pending or not self.auto_connect:
            return
        if self.connected:
            # Detect unplugging without disturbing the calculator.
            self.submit(lambda p: self.link.probe(), on_done=lambda pids: pids or self._lost(), quiet=True)
        else:
            self.submit(lambda p: self.link.probe(), on_done=self._probed, quiet=True)

    def _probed(self, pids) -> None:
        if pids and not self.connected and self._state != "connecting":
            self.connect_link()

    def _lost(self) -> None:
        self.message.emit("info", "Calculadora desconectada")
        self.disconnect_link()

    def connect_link(self) -> None:
        self._set_state("connecting")

        def work(p):
            self.link.open()
            return self.link.info()

        def ok(info):
            self.device = info
            self._set_state("connected")
            self.info.emit(info)
            self.message.emit("ok", f"Conectada: {info.product_name}")

        def fail(err):
            self._set_state("disconnected")
            self.message.emit("error", f"No se pudo conectar: {err}")

        self.submit(work, ok, fail, quiet=True)

    def disconnect_link(self) -> None:
        self.device = None
        self.submit(lambda p: self.link.close(), quiet=True)
        self._set_state("disconnected")
        self.info.emit(None)

    def refresh_info(self) -> None:
        def ok(info):
            self.device = info
            self.info.emit(info)
        self.submit(lambda p: self.link.info(), ok)

    def submit(self, fn, on_done=None, on_fail=None, on_progress=None, quiet: bool = False) -> Task:
        """Queue a link operation. Errors also go to ``message`` unless handled."""
        self._pending += 1
        if not quiet and self.connected:
            self._set_state("busy")

        def finish():
            self._pending -= 1
            if self._state == "busy" and not self._pending:
                self._set_state("connected" if self.link.is_open else "disconnected")

        def done(result):
            finish()
            if on_done:
                on_done(result)

        def failed(err):
            finish()
            log.warning("operación USB fallida: %s", err)
            if on_fail:
                on_fail(err)
            else:
                self.message.emit("error", err)
            if not self.link.is_open and self.connected:
                self._set_state("disconnected")

        return run_task(fn, done, failed, on_progress, pool=self.pool)

    def shutdown(self) -> None:
        self._timer.stop()
        self.pool.clear()
        self.pool.waitForDone(3000)
        try:
            self.link.close()
        except LinkError:
            pass


__all__ = ["LinkService", "run_task", "Task", "ERR_NOT_FOUND", "MockLink"]
