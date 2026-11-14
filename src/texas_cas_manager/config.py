"""User settings and safe file helpers."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "Texas CAS Manager"
APP_ID = "texas-cas-manager"


def config_dir() -> Path:
    """Resolved on each call so XDG_CONFIG_HOME set later (e.g. by tests) is honoured."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_ID


def log_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / APP_ID


def default_workspace() -> str:
    return str(Path.home() / "Documentos" / "TI-Nspire")

MAX_RECENT = 10

log = logging.getLogger(APP_ID)


@dataclass
class Settings:
    theme: str = "system"  # system | light | dark
    workspace: str = field(default_factory=default_workspace)
    demo_mode: bool = False  # simulated calculator, no USB
    auto_connect: bool = True
    recent: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_dir() / "settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "settings.json"
        atomic_write(path, json.dumps(asdict(self), indent=2, ensure_ascii=False).encode("utf-8"), overwrite=True)

    def add_recent(self, file: str) -> None:
        self.recent = [file] + [f for f in self.recent if f != file]
        del self.recent[MAX_RECENT:]


def atomic_write(path: Path, data: bytes, overwrite: bool = False) -> None:
    """Write through a temporary file + rename. Refuses to replace a file unless ``overwrite``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"ya existe: {path}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if overwrite:
            os.replace(tmp, path)
        else:
            os.link(tmp, path)  # fails if path appeared meanwhile; never clobbers
            os.unlink(tmp)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def unique_path(path: Path) -> Path:
    """``path`` if free, else ``stem (2).ext``, ``stem (3).ext``..."""
    path = Path(path)
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem} ({n}){path.suffix}")).exists():
        n += 1
    return candidate


def setup_logging() -> Path:
    logdir = log_dir()
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / "app.log"
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(logfile, encoding="utf-8"), logging.StreamHandler()],
    )
    return logfile
