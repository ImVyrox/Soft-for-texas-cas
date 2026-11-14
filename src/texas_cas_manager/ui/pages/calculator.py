"""Calculator page: computer files on the left, calculator files on the right."""

from __future__ import annotations

import posixpath
from pathlib import Path

from PySide6.QtCore import QDir, QMimeData, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFileSystemModel, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QProgressBar, QPushButton, QSplitter,
                               QToolBar, QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...config import unique_path
from PySide6.QtCore import QTimer

from ...core.link import ERR_BUSY, RemoteEntry, join
from ..widgets.common import Card, confirm, human_size, icon, label

REMOTE_MIME = "application/x-tcm-remote-paths"
PATH_ROLE = Qt.UserRole
DIR_ROLE = Qt.UserRole + 1
LOADED_ROLE = Qt.UserRole + 2
SIZE_ROLE = Qt.UserRole + 3


class LocalTree(QTreeView):
    """Local files; accepts calculator files dropped from the remote tree."""

    remote_dropped = Signal(list, str)  # remote paths, local folder

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def _target_dir(self, pos) -> str:
        model: QFileSystemModel = self.model()
        idx = self.indexAt(pos)
        if not idx.isValid():
            return model.filePath(self.rootIndex())
        path = model.filePath(idx)
        return path if model.isDir(idx) else str(Path(path).parent)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasFormat(REMOTE_MIME):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):  # noqa: N802
        if e.mimeData().hasFormat(REMOTE_MIME):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):  # noqa: N802
        if e.mimeData().hasFormat(REMOTE_MIME):
            paths = bytes(e.mimeData().data(REMOTE_MIME)).decode("utf-8").split("\n")
            self.remote_dropped.emit([p for p in paths if p], self._target_dir(e.position().toPoint()))
            e.acceptProposedAction()
        # Local-to-local moves are deliberately not handled here (no accidental moves).


class RemoteTree(QTreeWidget):
    """Calculator files; accepts local files and drags calculator files out."""

    local_dropped = Signal(list, str)  # local paths, remote folder

    def __init__(self):
        super().__init__()
        self.setColumnCount(3)
        self.setHeaderLabels(["Nombre", "Tamaño", "Tipo"])
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.AscendingOrder)

    def mimeTypes(self):  # noqa: N802
        return [REMOTE_MIME]

    def mimeData(self, items):  # noqa: N802
        md = QMimeData()
        paths = [it.data(0, PATH_ROLE) for it in items if not it.data(0, DIR_ROLE)]
        md.setData(REMOTE_MIME, "\n".join(paths).encode("utf-8"))
        return md

    def folder_at(self, pos) -> str:
        it = self.itemAt(pos)
        if it is None:
            return "/"
        path = it.data(0, PATH_ROLE)
        return path if it.data(0, DIR_ROLE) else posixpath.dirname(path)

    def dragEnterEvent(self, e):  # noqa: N802
        e.acceptProposedAction() if e.mimeData().hasUrls() else e.ignore()

    def dragMoveEvent(self, e):  # noqa: N802
        e.acceptProposedAction() if e.mimeData().hasUrls() else e.ignore()

    def dropEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            self.local_dropped.emit(files, self.folder_at(e.position().toPoint()))
            e.acceptProposedAction()


class CalculatorPage(QWidget):
    open_document = Signal(str)

    def __init__(self, service, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.service = service
        self.settings = settings
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label("Calculadora", "title"))
        head.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en la calculadora…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._filter)
        head.addWidget(self.search)
        root.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # Left: computer
        left = Card("Este ordenador")
        bar = QHBoxLayout()
        self.local_path = QLineEdit()
        self.local_path.setReadOnly(True)
        choose = QPushButton(icon("folder"), "Carpeta…")
        choose.clicked.connect(self._choose_folder)
        bar.addWidget(self.local_path, 1)
        bar.addWidget(choose)
        left.body.addLayout(bar)
        self.fs = QFileSystemModel(self)
        self.fs.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.local = LocalTree()
        self.local.setModel(self.fs)
        for col in (2, 3):
            self.local.hideColumn(col)
        self.local.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.local.doubleClicked.connect(self._local_activated)
        self.local.remote_dropped.connect(self.download)
        left.body.addWidget(self.local, 1)
        self.upload_btn = QPushButton(icon("upload"), "Enviar a la calculadora")
        self.upload_btn.setProperty("kind", "primary")
        self.upload_btn.clicked.connect(self._upload_selected)
        left.body.addWidget(self.upload_btn, 0, Qt.AlignRight)
        split.addWidget(left)

        # Right: calculator
        right = Card("TI-Nspire")
        tb = QToolBar()
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)  # tooltips carry the names; fits narrow panes
        self.act_refresh = tb.addAction(icon("refresh"), "Actualizar", self.refresh)
        self.act_download = tb.addAction(icon("download"), "Descargar", self._download_selected)
        self.act_mkdir = tb.addAction(icon("folder-new"), "Carpeta", self._mkdir)
        self.act_rename = tb.addAction(icon("rename"), "Renombrar", self._rename)
        self.act_delete = tb.addAction(icon("delete"), "Eliminar", self._delete)
        right.body.addWidget(tb)
        self.remote = RemoteTree()
        self.remote.itemExpanded.connect(self._expand)
        self.remote.local_dropped.connect(self.upload)
        self.remote.itemSelectionChanged.connect(self._update_actions)
        right.body.addWidget(self.remote, 1)
        self.remote_hint = label("Arrastra archivos .tns aquí para enviarlos.", "muted")
        rbar = QHBoxLayout()
        rbar.addWidget(self.remote_hint, 1)
        self.download_btn = QPushButton(icon("download"), "Descargar al ordenador")
        self.download_btn.setProperty("kind", "primary")
        self.download_btn.clicked.connect(self._download_selected)
        rbar.addWidget(self.download_btn)
        right.body.addLayout(rbar)
        split.addWidget(right)
        split.setSizes([500, 600])

        # Transfer bar
        self.status = QLabel("")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(260)
        self.progress.hide()
        tbar = QHBoxLayout()
        tbar.addWidget(self.status, 1)
        tbar.addWidget(self.progress)
        root.addLayout(tbar)

        # Automatic retry while the calculator reports "busy" (ERR_BUSY): the request was
        # acknowledged but not answered. Bounded and shown in the status line.
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry_busy)
        self._busy_attempts = 0
        self.set_local_root(settings.workspace)
        self.service.state.connect(self._on_state)
        self._on_state("disconnected")

    # -- local side ----------------------------------------------------------

    def set_local_root(self, folder: str) -> None:
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.fs.setRootPath(folder)
        self.local.setRootIndex(self.fs.index(folder))
        self.local_path.setText(folder)

    def _choose_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Carpeta local", self.local_path.text())
        if d:
            self.set_local_root(d)

    def _local_dir(self) -> str:
        idx = self.local.currentIndex()
        if idx.isValid():
            p = self.fs.filePath(idx)
            return p if self.fs.isDir(idx) else str(Path(p).parent)
        return self.local_path.text()

    def _local_activated(self, idx) -> None:
        if not self.fs.isDir(idx) and self.fs.filePath(idx).lower().endswith(".tns"):
            self.open_document.emit(self.fs.filePath(idx))

    # -- remote side ---------------------------------------------------------

    def _on_state(self, state: str) -> None:
        on = state in ("connected", "busy")
        self.remote.setEnabled(on)
        self.upload_btn.setEnabled(on)
        self.act_refresh.setEnabled(on)
        if state == "connected" and self.remote.topLevelItemCount() == 0:
            self.refresh()
        if state == "disconnected":
            self._retry_timer.stop()
            self._busy_attempts = 0
            self.remote.clear()
            self.remote_hint.setText("Calculadora no conectada.")
        elif on:
            self.remote_hint.setText("Arrastra archivos .tns aquí para enviarlos.")
        self._update_actions()

    def _update_actions(self) -> None:
        sel = self.remote.selectedItems()
        on = self.service.connected
        can_download = on and any(not i.data(0, DIR_ROLE) for i in sel)
        self.act_download.setEnabled(can_download)
        self.download_btn.setEnabled(can_download)
        self.act_delete.setEnabled(on and bool(sel))
        self.act_rename.setEnabled(on and len(sel) == 1)
        self.act_mkdir.setEnabled(on)

    def _make_item(self, e: RemoteEntry) -> QTreeWidgetItem:
        it = QTreeWidgetItem([e.name, "" if e.is_dir else human_size(e.size),
                              "Carpeta" if e.is_dir else (Path(e.name).suffix[1:].upper() or "Archivo")])
        it.setIcon(0, icon("folder" if e.is_dir else "file"))
        it.setData(0, PATH_ROLE, e.path)
        it.setData(0, DIR_ROLE, e.is_dir)
        it.setData(0, SIZE_ROLE, e.size)
        it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        if e.is_dir:
            it.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        return it

    def _children_parent(self, folder: str):
        if folder == "/":
            return None
        for it in self._all_items():
            if it.data(0, PATH_ROLE) == folder and it.data(0, DIR_ROLE):
                return it
        return False  # folder not shown

    def _all_items(self):
        stack = [self.remote.topLevelItem(i) for i in range(self.remote.topLevelItemCount())]
        while stack:
            it = stack.pop()
            yield it
            stack.extend(it.child(i) for i in range(it.childCount()))

    def load_folder(self, folder: str) -> None:
        def done(entries):
            parent = self._children_parent(folder)
            if parent is False:
                return
            if parent is None:
                self.remote.clear()
            else:
                parent.takeChildren()
                parent.setData(0, LOADED_ROLE, True)
            items = [self._make_item(e) for e in entries]
            if parent is None:
                self.remote.addTopLevelItems(items)
            else:
                parent.addChildren(items)
                if not items:
                    parent.setChildIndicatorPolicy(QTreeWidgetItem.DontShowIndicatorWhenChildless)
            self._filter(self.search.text())
            self.status.setText(f"{folder}: {len(entries)} elementos")

        def failed(err):
            if getattr(err, "code", None) == ERR_BUSY and folder == "/" and self._busy_attempts < self.BUSY_RETRIES:
                self._busy_attempts += 1
                self.status.setText(f"Calculadora ocupada: nuevo intento en {self.BUSY_DELAY_S} s "
                                    f"({self._busy_attempts}/{self.BUSY_RETRIES}). Pulsa Actualizar para reintentar ya.")
                self._retry_timer.start(self.BUSY_DELAY_S * 1000)
            else:
                self.status.setText(f"No se pudo leer {folder}")
            self.service.message.emit("error", str(err))

        self.status.setText(f"Leyendo {folder}…")
        self.service.submit(lambda p: self.service.link.list(folder), self._listed(done), failed)

    BUSY_RETRIES = 4
    BUSY_DELAY_S = 20  # the busy state lasted 45-60 s in tests on OS 4.5.5

    def _listed(self, done):
        def wrapper(entries):
            self._busy_attempts = 0
            done(entries)
        return wrapper

    def _retry_busy(self) -> None:
        if self.service.connected:
            self.load_folder("/")

    def refresh(self) -> None:
        self._retry_timer.stop()
        self._busy_attempts = 0
        expanded = [it.data(0, PATH_ROLE) for it in self._all_items() if it.isExpanded()]
        self.load_folder("/")
        for path in expanded:
            self.load_folder(path)

    def _expand(self, item) -> None:
        if not item.data(0, LOADED_ROLE):
            self.load_folder(item.data(0, PATH_ROLE))

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for it in self._all_items():
            it.setHidden(bool(text) and not it.data(0, DIR_ROLE) and text not in it.text(0).lower())

    def _selected_folder(self) -> str:
        sel = self.remote.selectedItems()
        if not sel:
            return "/"
        p = sel[0].data(0, PATH_ROLE)
        return p if sel[0].data(0, DIR_ROLE) else posixpath.dirname(p)

    def _existing_names(self, folder: str) -> set[str]:
        parent = self._children_parent(folder)
        if parent is None:
            items = [self.remote.topLevelItem(i) for i in range(self.remote.topLevelItemCount())]
        elif parent is False:
            return set()
        else:
            items = [parent.child(i) for i in range(parent.childCount())]
        return {it.text(0) for it in items}

    # -- transfers -----------------------------------------------------------

    def _run_batch(self, title: str, jobs: list, after_folder: str | None, on_finish=None) -> None:
        """Run ``jobs`` (list of (description, fn(progress))) one after another."""
        if not jobs:
            return
        self.progress.show()
        state = {"i": 0, "errors": []}

        def step():
            if state["i"] >= len(jobs):
                self.progress.hide()
                n_err = len(state["errors"])
                msg = f"{title}: {len(jobs) - n_err} de {len(jobs)} completados"
                self.status.setText(msg)
                self.service.message.emit("error" if n_err else "ok",
                                          msg + ("\n" + "\n".join(state["errors"]) if n_err else ""))
                if after_folder:
                    self.load_folder(after_folder)
                if on_finish:
                    on_finish()
                return
            desc, fn = jobs[state["i"]]
            self.status.setText(f"{desc} ({state['i'] + 1}/{len(jobs)})")
            self.progress.setRange(0, 0)

            def prog(done, total):
                self.progress.setRange(0, max(total, 1))
                self.progress.setValue(done)

            def ok(_):
                state["i"] += 1
                step()

            def fail(err):
                state["errors"].append(f"{desc}: {err.splitlines()[0]}")
                state["i"] += 1
                step()

            self.service.submit(fn, ok, fail, prog)

        step()

    def upload(self, files: list[str], folder: str) -> None:
        files = [f for f in files if Path(f).is_file()]
        bad = [Path(f).name for f in files if not f.lower().endswith(".tns")]
        if bad:
            self.service.message.emit("error", "La calculadora solo acepta documentos .tns. Omitidos: " + ", ".join(bad))
        files = [f for f in files if f.lower().endswith(".tns")]
        existing = self._existing_names(folder) & {Path(f).name for f in files}
        if existing and not confirm(self, "Reemplazar en la calculadora",
                                    "Ya existen en la calculadora:\n" + "\n".join(sorted(existing)) +
                                    "\n\n¿Reemplazarlos?", danger=True):
            return
        jobs = []
        for f in files:
            remote = join(folder, Path(f).name)
            jobs.append((f"Enviando {Path(f).name}", lambda p, f=f, r=remote: self.service.link.put(Path(f), r, p)))
        self._run_batch("Envío", jobs, folder)

    def _upload_selected(self) -> None:
        idxs = [i for i in self.local.selectionModel().selectedRows(0) if not self.fs.isDir(i)]
        if not idxs:
            self.service.message.emit("info", "Selecciona archivos .tns en el panel izquierdo.")
            return
        self.upload([self.fs.filePath(i) for i in idxs], self._selected_folder())

    def download(self, remotes: list[str], local_dir: str) -> None:
        jobs = []
        planned: set[Path] = set()
        for r in remotes:
            target = unique_path(Path(local_dir) / posixpath.basename(r))
            while target in planned:  # same name twice in one batch
                target = target.with_name(f"_{target.name}")
            planned.add(target)
            jobs.append((f"Descargando {posixpath.basename(r)}",
                         lambda p, r=r, t=target: self.service.link.get(r, t, p)))
        self._run_batch("Descarga", jobs, None)

    def _download_selected(self) -> None:
        remotes = [i.data(0, PATH_ROLE) for i in self.remote.selectedItems() if not i.data(0, DIR_ROLE)]
        self.download(remotes, self._local_dir())

    def _mkdir(self) -> None:
        parent = self._selected_folder()
        name, ok = QInputDialog.getText(self, "Nueva carpeta", f"Nombre de la carpeta en {parent}:")
        name = name.strip()
        if not ok or not name:
            return
        if "/" in name:
            self.service.message.emit("error", "El nombre no puede contener «/».")
            return
        path = join(parent, name)
        self.service.submit(lambda p: self.service.link.mkdir(path), lambda _: self.load_folder(parent))

    def _rename(self) -> None:
        it = self.remote.selectedItems()[0]
        old = it.data(0, PATH_ROLE)
        name, ok = QInputDialog.getText(self, "Renombrar", "Nuevo nombre:", text=posixpath.basename(old))
        name = name.strip()
        if not ok or not name or name == posixpath.basename(old):
            return
        if "/" in name or (not it.data(0, DIR_ROLE) and not name.lower().endswith(".tns")
                           and old.lower().endswith(".tns")):
            self.service.message.emit("error", "Nombre no válido (los documentos deben terminar en .tns).")
            return
        folder = posixpath.dirname(old)
        new = join(folder, name)
        self.service.submit(lambda p: self.service.link.rename(old, new), lambda _: self.load_folder(folder))

    def _delete(self) -> None:
        sel = self.remote.selectedItems()
        names = [i.data(0, PATH_ROLE) for i in sel]
        if not confirm(self, "Eliminar de la calculadora",
                       "Se eliminarán de la calculadora (no se puede deshacer):\n\n" + "\n".join(names) +
                       "\n\nLas carpetas solo se eliminan si están vacías.", danger=True):
            return
        jobs = []
        folders = set()
        for it in sel:
            path = it.data(0, PATH_ROLE)
            folders.add(posixpath.dirname(path))
            if it.data(0, DIR_ROLE):
                jobs.append((f"Eliminando carpeta {path}", lambda p, x=path: self.service.link.rmdir(x)))
            else:
                jobs.append((f"Eliminando {path}", lambda p, x=path: self.service.link.delete(x)))
        self._run_batch("Eliminación", jobs, None, on_finish=lambda: [self.load_folder(f) for f in folders])
