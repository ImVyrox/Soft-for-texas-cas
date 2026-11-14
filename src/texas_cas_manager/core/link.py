"""Calculator link: talks to the ``tcm-link`` helper process over JSON lines.

The helper (native/tcm-link) wraps libticalcs2. Every method here blocks, so
the GUI calls them from worker threads (see ui/workers.py). A lock serialises
requests because the calculator handles one operation at a time.

The calculator-side quirks (persistent file session, packets sent by the
calculator after a transfer) are handled inside the helper; see
docs/USB-PROTOCOL.md.
"""

from __future__ import annotations

import json
import os
import posixpath
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

ProgressFn = Callable[[int, int], None]

TI_VENDOR_PIDS = {0xE012: "TI-Nspire (CX)", 0xE022: "TI-Nspire CX II"}
ERR_TIMEOUT = 4  # libticables: no packet at all (cable, power, or the request was not acknowledged)
ERR_CALC_STATUS = 1000  # tcm-link: calculator status reply "FF xx" -> 1000 + xx
ERR_NOT_FOUND = ERR_CALC_STATUS + 0x0A
ERR_BUSY = 9007  # tcm-link: request acknowledged but never answered (file service busy)
ERR_HELPER = -1

# Calculator status bytes documented on Hackspire (USB Protocol, file management).
CALC_STATUS_TEXT = {
    0x09: "la carpeta de destino no existe",
    0x0A: "el archivo o la carpeta no existe",
    0x0F: "nombre de carpeta no válido",
    0x14: "nombre de archivo no válido",
    0x15: "los documentos deben tener extensión .tns",
}


def describe_error(code: int, raw: str) -> str:
    """Spanish explanation for a helper error, keeping the original text."""
    if code == ERR_BUSY:
        return ("La calculadora recibió la petición pero no respondió: su servicio de archivos está "
                "ocupado. Pasa, por ejemplo, al pedir el documento que tiene abierto; suele "
                "recuperarse sola en alrededor de un minuto.")
    if code == ERR_TIMEOUT:
        return ("La calculadora no contesta. Comprueba el cable y que esté encendida.\n" + raw)
    if ERR_CALC_STATUS <= code < ERR_CALC_STATUS + 256:
        status = code - ERR_CALC_STATUS
        return f"La calculadora rechazó la operación: {CALC_STATUS_TEXT.get(status, f'código 0x{status:02X}')}."
    return raw


class LinkError(Exception):
    def __init__(self, message: str, code: int = ERR_HELPER):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RemoteEntry:
    path: str
    size: int
    is_dir: bool

    @property
    def name(self) -> str:
        return posixpath.basename(self.path)


@dataclass(frozen=True)
class DeviceInfo:
    product_name: str
    os_version: str
    boot2_version: str
    flash_free: int
    flash_total: int
    ram_free: int
    ram_total: int
    battery_ok: bool
    product_id: str = ""

    @classmethod
    def from_reply(cls, r: dict) -> "DeviceInfo":
        return cls(r.get("product_name", ""), r.get("os_version", ""), r.get("boot2_version", ""),
                   int(r.get("flash_free", 0)), int(r.get("flash_total", 0)),
                   int(r.get("ram_free", 0)), int(r.get("ram_total", 0)),
                   bool(r.get("battery_ok", True)), r.get("product_id", ""))


def check_remote_path(path: str) -> str:
    """Validate an absolute calculator path; returns it unchanged."""
    if not path.startswith("/") or any(c in path for c in "\t\n\r\0"):
        raise LinkError(f"ruta de calculadora no válida: {path!r}")
    if any(part in (".", "..") for part in path.split("/")):
        raise LinkError(f"ruta de calculadora no válida: {path!r}")
    return path


def join(folder: str, name: str) -> str:
    return check_remote_path(posixpath.join(folder or "/", name))


class Link(Protocol):
    """Operations the GUI needs; implemented by HelperLink and MockLink."""

    def probe(self) -> list[int]: ...
    def open(self) -> None: ...
    def close(self) -> None: ...
    @property
    def is_open(self) -> bool: ...
    def info(self) -> DeviceInfo: ...
    def list(self, folder: str) -> list[RemoteEntry]: ...
    def get(self, remote: str, local: Path, progress: ProgressFn | None = None) -> int: ...
    def put(self, local: Path, remote: str, progress: ProgressFn | None = None) -> int: ...
    def delete(self, remote: str) -> None: ...
    def mkdir(self, remote: str) -> None: ...
    def rmdir(self, remote: str) -> None: ...
    def rename(self, src: str, dst: str) -> None: ...


def find_helper() -> str | None:
    env = os.environ.get("TCM_LINK")
    if env:
        return env
    repo = Path(__file__).resolve().parents[3] / "native" / "tcm-link" / "tcm-link"
    if repo.is_file() and os.access(repo, os.X_OK):
        return str(repo)
    return shutil.which("tcm-link")


class HelperLink:
    """Link through the ``tcm-link`` helper process."""

    def __init__(self, helper: str | None = None, log_path: Path | None = None):
        self._helper = helper or find_helper()
        self.log_path = log_path  # helper stderr (libticalcs messages); None = discard
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._next_id = 0
        self._open = False

    # -- process / protocol -------------------------------------------------

    def _ensure_process(self) -> subprocess.Popen:
        if self._proc and self._proc.poll() is None:
            return self._proc
        if not self._helper:
            raise LinkError("no se encontró el programa auxiliar tcm-link (ejecuta scripts/build-helper.sh)")
        self._open = False
        env = dict(os.environ)
        if os.environ.get("TCM_DEBUG"):
            env["G_MESSAGES_DEBUG"] = "all"  # libticalcs logs every USB packet
        log = None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log = open(self.log_path, "a", encoding="utf-8")
        try:
            self._proc = subprocess.Popen(
                [self._helper], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=log or subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1, env=env)
        finally:
            if log:
                log.close()  # the child keeps its own descriptor
        return self._proc

    def _request(self, *args: str, progress: ProgressFn | None = None) -> dict:
        for a in args:
            if any(c in a for c in "\t\n\r"):
                raise LinkError(f"argumento no válido: {a!r}")
        with self._lock:
            proc = self._ensure_process()
            self._next_id += 1
            rid = str(self._next_id)
            try:
                proc.stdin.write("\t".join((rid, *args)) + "\n")
                proc.stdin.flush()
            except OSError as exc:
                self._open = False
                raise LinkError(f"el programa auxiliar terminó: {exc}") from exc
            while True:
                line = proc.stdout.readline()
                if not line:
                    self._open = False
                    raise LinkError("el programa auxiliar terminó inesperadamente")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # never expected; stdout carries only JSON
                if msg.get("id") != rid:
                    continue
                if msg.get("event") == "progress":
                    if progress:
                        progress(int(msg["done"]), int(msg["total"]))
                    continue
                if not msg.get("ok"):
                    code = int(msg.get("code", ERR_HELPER))
                    raise LinkError(describe_error(code, msg.get("error", "error desconocido").strip()), code)
                return msg

    # -- Link API -------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._open

    def probe(self) -> list[int]:
        return [int(p) for p in self._request("probe").get("pids", [])]

    def open(self) -> None:
        self._request("open")
        self._open = True

    def close(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._request("quit")
                except LinkError:
                    pass
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
            self._open = False

    def info(self) -> DeviceInfo:
        return DeviceInfo.from_reply(self._request("info"))

    def list(self, folder: str) -> list[RemoteEntry]:
        folder = check_remote_path(folder)
        reply = self._request("list", folder)
        return [RemoteEntry(posixpath.join(folder, it["name"]), int(it["size"]), int(it["type"]) == 1)
                for it in reply["items"]]

    def get(self, remote: str, local: Path, progress: ProgressFn | None = None) -> int:
        reply = self._request("get", check_remote_path(remote), str(local), progress=progress)
        return int(reply["size"])

    def put(self, local: Path, remote: str, progress: ProgressFn | None = None) -> int:
        return int(self._request("put", str(local), check_remote_path(remote), progress=progress)["size"])

    def delete(self, remote: str) -> None:
        self._request("del", check_remote_path(remote))

    def mkdir(self, remote: str) -> None:
        self._request("mkdir", check_remote_path(remote))

    def rmdir(self, remote: str) -> None:
        self._request("rmdir", check_remote_path(remote))

    def rename(self, src: str, dst: str) -> None:
        self._request("rename", check_remote_path(src), check_remote_path(dst))


class MockLink:
    """In-memory calculator for tests and the demo mode. Never touches USB."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files: dict[str, bytes] = dict(files or {})
        self.dirs: set[str] = {"/"}
        for p in self.files:
            while (p := posixpath.dirname(p)) != "/":
                self.dirs.add(p)
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def _need_open(self):
        if not self._open:
            raise LinkError("link is not open", 9002)

    def probe(self) -> list[int]:
        return [0xE012]

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def info(self) -> DeviceInfo:
        self._need_open()
        used = sum(len(d) for d in self.files.values())
        return DeviceInfo("TI-Nspire CX CAS (simulada)", "4.5.5.79", "4.5.0.14",
                          120_000_000 - used, 120_000_000, 27_000_000, 35_000_000, True)

    def list(self, folder: str) -> list[RemoteEntry]:
        self._need_open()
        folder = check_remote_path(folder)
        if folder not in self.dirs:
            raise LinkError("Msg: the variable or directory does not exist.", ERR_NOT_FOUND)
        out = [RemoteEntry(d, 0, True) for d in sorted(self.dirs) if d != "/" and posixpath.dirname(d) == folder]
        out += [RemoteEntry(p, len(b), False) for p, b in sorted(self.files.items()) if posixpath.dirname(p) == folder]
        return out

    def get(self, remote: str, local: Path, progress: ProgressFn | None = None) -> int:
        self._need_open()
        if remote not in self.files:
            raise LinkError("Msg: the variable or directory does not exist.", ERR_NOT_FOUND)
        data = self.files[remote]
        tmp = Path(str(local) + ".part")
        tmp.write_bytes(data)
        tmp.replace(local)
        if progress:
            progress(len(data), len(data))
        return len(data)

    def put(self, local: Path, remote: str, progress: ProgressFn | None = None) -> int:
        self._need_open()
        check_remote_path(remote)
        if posixpath.dirname(remote) not in self.dirs:
            raise LinkError("Msg: the variable or directory does not exist.", ERR_NOT_FOUND)
        data = Path(local).read_bytes()
        self.files[remote] = data
        if progress:
            progress(len(data), len(data))
        return len(data)

    def delete(self, remote: str) -> None:
        self._need_open()
        if self.files.pop(remote, None) is None:
            raise LinkError("Msg: the variable or directory does not exist.", ERR_NOT_FOUND)

    def mkdir(self, remote: str) -> None:
        self._need_open()
        if remote in self.dirs or posixpath.dirname(remote) not in self.dirs:
            raise LinkError("cannot create folder", 400)
        self.dirs.add(remote)

    def rmdir(self, remote: str) -> None:
        self._need_open()
        if remote not in self.dirs or remote == "/" or any(posixpath.dirname(p) == remote for p in [*self.files, *self.dirs]):
            raise LinkError("cannot delete folder", 400)
        self.dirs.discard(remote)

    def rename(self, src: str, dst: str) -> None:
        self._need_open()
        if src not in self.files or dst in self.files:
            raise LinkError("cannot rename", 400)
        self.files[dst] = self.files.pop(src)
