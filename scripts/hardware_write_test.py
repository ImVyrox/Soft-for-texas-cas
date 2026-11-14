#!/usr/bin/env python3
"""Guarded write test against a real TI-Nspire (authorised scope: /TCM_TESTS only).

Steps: create /TCM_TESTS, upload a generated .tns, list, download, compare
SHA-256, rename, list, delete, list. Before and after, the personal files are
snapshotted (recursive listing + SHA-256 of every downloadable file) and
compared. Every write is checked against the allowed folder first. The run
stops at the first failure and never repeats a write.

Usage:  PYTHONPATH=src .venv/bin/python scripts/hardware_write_test.py OUT_DIR [--mock]
        --mock runs the same sequence against the simulated calculator (no USB).
Writes OUT_DIR/report.json and prints one line per operation.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import sys
import time
from pathlib import Path

from texas_cas_manager.core.link import HelperLink, LinkError
from texas_cas_manager.tns.lua import build_lua_document

TEST_DIR = "/TCM_TESTS"
TEST_FILE = f"{TEST_DIR}/tcm_prueba.tns"
RENAMED_FILE = f"{TEST_DIR}/tcm_prueba_renombrada.tns"
# Files the calculator does not hand over (no reply, seen 2026-11-13): the open document and
# the system log. They are compared by listing (name, size) only.
SKIP_DOWNLOAD = {"/Ejemplos/P2.tns", "/NspireLogs.zip"}


class Abort(Exception):
    pass


def assert_in_test_dir(path: str, allow_dir_itself: bool = False) -> None:
    """Refuse any write outside /TCM_TESTS (normalised, no '..')."""
    norm = posixpath.normpath(path)
    if norm != path or ".." in path.split("/"):
        raise Abort(f"ruta no normalizada, rechazada: {path!r}")
    if allow_dir_itself and norm == TEST_DIR:
        return
    if posixpath.dirname(norm) != TEST_DIR:
        raise Abort(f"ruta fuera de {TEST_DIR}, rechazada: {path!r}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "operations": []}
    if "--mock" in sys.argv:
        from texas_cas_manager.core.link import MockLink
        link = MockLink({"/potenciales.tns": b"P" * 100, "/Ejemplos/P2.tns": b"2" * 50,
                         "/MyWidgets/stopwatch.tns": b"S" * 70, "/MyLib/Ejemplos/x.tns": b"x"})
    else:
        link = HelperLink(log_path=out / "tcm-link.log")

    def op(name: str, executed: str, fn, verify=None):
        t = time.time()
        entry = {"op": name, "executed": executed}
        try:
            entry["calculator_reply"] = fn()
            entry["ok"] = True
        except LinkError as e:
            entry.update(ok=False, calculator_reply=f"error {e.code}: {e}")
        entry["seconds"] = round(time.time() - t, 2)
        if entry["ok"] and verify:
            entry["verification"], entry["verified"] = verify(entry["calculator_reply"])
        report["operations"].append(entry)
        status = "OK " if entry["ok"] and entry.get("verified", True) else "FALLO"
        print(f"[{status}] {name}: {entry['calculator_reply']} | {entry.get('verification', '')}", flush=True)
        if not entry["ok"] or not entry.get("verified", True):
            raise Abort(f"se detiene en «{name}»")
        return entry["calculator_reply"]

    def listing(folder: str) -> dict[str, tuple[int, bool]]:
        return {e.path: (e.size, e.is_dir) for e in link.list(folder)}

    def snapshot(tag: str) -> dict:
        tree, stack = {}, ["/"]
        while stack:
            folder = stack.pop()
            for path, (size, is_dir) in listing(folder).items():
                if path == TEST_DIR or path.startswith(TEST_DIR + "/"):
                    continue  # the test folder is not personal data
                tree[path] = {"size": size, "dir": is_dir}
                if is_dir:
                    stack.append(path)
        snap_dir = out / f"snapshot-{tag}"
        snap_dir.mkdir(exist_ok=True)
        for path, info in sorted(tree.items()):
            if info["dir"] or path in SKIP_DOWNLOAD:
                continue
            local = snap_dir / path.strip("/").replace("/", "__")
            link.get(path, local)
            info["sha256"] = sha256(local)
        return tree

    try:
        op("Conectar", "open + info", lambda: (link.open(), link.info().os_version)[1])

        before = op("Instantánea previa de archivos personales",
                    "listado recursivo + descarga y SHA-256 de cada archivo (solo lectura)",
                    lambda: snapshot("antes"),
                    lambda r: (f"{len(r)} elementos; solo por listado: {sorted(SKIP_DOWNLOAD)}", True))
        report["personal_before"] = before

        local_doc = out / "tcm_prueba.tns"
        local_doc.write_bytes(build_lua_document(
            "-- Archivo de prueba de Texas CAS Manager (se puede borrar)\n"
            f"-- generado {report['date']}\n"
            'function on.paint(gc) gc:drawString("TCM prueba", 10, 10) end\n'))
        original_sha = sha256(local_doc)
        report["local_file"] = {"path": str(local_doc), "size": local_doc.stat().st_size, "sha256": original_sha}

        root = listing("/")
        if TEST_DIR in root:
            report["operations"].append({"op": "1. Crear carpeta", "executed": "no ejecutado",
                                         "calculator_reply": f"{TEST_DIR} ya existía", "ok": True})
            print(f"[OK ] 1. Crear carpeta: {TEST_DIR} ya existía, no se crea", flush=True)
        else:
            assert_in_test_dir(TEST_DIR, allow_dir_itself=True)
            def created(_):
                entry = listing("/").get(TEST_DIR)
                return f"{TEST_DIR} en el listado de /: {entry}", bool(entry and entry[1])
            op("1. Crear carpeta", f"mkdir {TEST_DIR}", lambda: link.mkdir(TEST_DIR) or "FF 00 (éxito)", created)

        existing = listing(TEST_DIR)
        for p in (TEST_FILE, RENAMED_FILE):
            if p in existing:
                raise Abort(f"{p} ya existe en la calculadora; no se sobrescribe")

        assert_in_test_dir(TEST_FILE)
        op("2. Enviar archivo", f"put {local_doc.name} -> {TEST_FILE}",
           lambda: f"{link.put(local_doc, TEST_FILE)} bytes enviados, FF 00 (éxito)")

        op("3. Verificar listado", f"list {TEST_DIR}", lambda: listing(TEST_DIR),
           lambda r: (f"{TEST_FILE} con {r.get(TEST_FILE, ('-',))[0]} bytes (local {local_doc.stat().st_size})",
                      r.get(TEST_FILE, (None,))[0] == local_doc.stat().st_size))

        back = out / "tcm_prueba.descargado.tns"
        op("4. Descargar de nuevo", f"get {TEST_FILE} -> {back.name}",
           lambda: f"{link.get(TEST_FILE, back)} bytes recibidos")

        op("5. Comparar SHA-256", "sha256(original) == sha256(descargado)",
           lambda: {"original": original_sha, "descargado": sha256(back)},
           lambda r: ("idénticos" if r["original"] == r["descargado"] else "DISTINTOS",
                      r["original"] == r["descargado"]))

        assert_in_test_dir(TEST_FILE)
        assert_in_test_dir(RENAMED_FILE)
        op("6. Renombrar", f"rename {TEST_FILE} -> {RENAMED_FILE}",
           lambda: link.rename(TEST_FILE, RENAMED_FILE) or "FF 00 (éxito)")

        op("7. Verificar nombre", f"list {TEST_DIR}", lambda: listing(TEST_DIR),
           lambda r: (f"nuevo presente: {RENAMED_FILE in r}; antiguo ausente: {TEST_FILE not in r}",
                      RENAMED_FILE in r and TEST_FILE not in r))

        assert_in_test_dir(RENAMED_FILE)
        op("8. Eliminar archivo de prueba", f"del {RENAMED_FILE}",
           lambda: link.delete(RENAMED_FILE) or "FF 00 (éxito)")

        op("9. Verificar eliminación", f"list {TEST_DIR}", lambda: listing(TEST_DIR),
           lambda r: (f"{RENAMED_FILE} ausente; contenido de {TEST_DIR}: {sorted(r) or 'vacío'}",
                      RENAMED_FILE not in r))

        after = op("Instantánea posterior de archivos personales",
                   "listado recursivo + descarga y SHA-256 (solo lectura)",
                   lambda: snapshot("despues"),
                   lambda r: (("idénticos al estado previo" if r == before else "CAMBIARON"), r == before))
        report["personal_after"] = after
        op("Carpeta de pruebas conservada", "list /", lambda: TEST_DIR in listing("/"),
           lambda r: (f"{TEST_DIR} sigue en la calculadora", bool(r)))
        report["result"] = "ok"
    except Abort as exc:
        report["result"] = f"detenido: {exc}"
        print(f"DETENIDO: {exc}", flush=True)
    finally:
        link.close()
        (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if report.get("result") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
