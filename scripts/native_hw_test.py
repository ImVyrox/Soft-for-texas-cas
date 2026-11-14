#!/usr/bin/env python3
"""Hardware test of an edited *native* document (authorised scope: /TCM_TESTS only).

    prepare ORIGINAL.tns OUT_DIR   local only: copy, edit one line of the script,
                                   rebuild, validate, compare, SHA-256 (report.json)
    upload  OUT_DIR                needs the user's authorisation (destination: the
                                   "remote" of OUT_DIR/report.json): checks the
                                   calculator state, uploads to /TCM_TESTS, lists,
                                   downloads back and compares SHA-256

The original file is only read. The upload refuses any path outside
/TCM_TESTS, refuses to overwrite an existing file there and stops at the
first error without retrying writes.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import shutil
import sys
import time
from pathlib import Path

from texas_cas_manager.tns import container, inspect, lua
from texas_cas_manager.tns.edit import compare_documents, rebuild, text_diff

TEST_DIR = "/TCM_TESTS"
REMOTE = f"{TEST_DIR}/stopwatch_tcm.tns"
OLD_LINE = "                : setLabel '0:00:00.00'"
NEW_LINE = "                : setLabel 'TCM 0:00:00.00'"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(original: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    copy = out / "stopwatch_original.tns"
    shutil.copy2(original, copy)
    data = copy.read_bytes()
    src = lua.read_script(container.parse(data))
    if src.count(OLD_LINE + "\n") != 1:
        raise SystemExit("la línea a modificar no aparece exactamente una vez; no se continúa")
    edited = src.replace(OLD_LINE + "\n", NEW_LINE + "\n")
    new = rebuild(data, edited)  # validates structure, reads the script back, checks other components
    result = out / "stopwatch_tcm.tns"
    result.write_bytes(new)
    cmp = compare_documents(data, new)
    report = {
        "original": {"path": str(original), "copy": str(copy), "size": len(data), "sha256": sha(copy)},
        "result": {"path": str(result), "size": len(new), "sha256": sha(result), "remote": REMOTE},
        "validation": inspect.validate_bytes(new) or "sin problemas",
        "comparison": {"level": cmp.level, "components": [(c.name, c.status) for c in cmp.components]},
        "diff": text_diff(src, edited, "original", "editado"),
        "original_unchanged": sha(original) == sha(copy),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def upload(out: Path) -> int:
    from texas_cas_manager.core.link import HelperLink, LinkError
    report = json.loads((out / "report.json").read_text())
    local = Path(report["result"]["path"])
    remote = report["result"]["remote"]
    if sha(local) != report["result"]["sha256"]:
        print("DETENIDO: el archivo preparado cambió desde la preparación")
        return 1
    if posixpath.dirname(remote) != TEST_DIR or posixpath.normpath(remote) != remote:
        print("DETENIDO: destino fuera de /TCM_TESTS")
        return 1
    link = HelperLink(log_path=out / "tcm-link.log")
    steps = []

    def step(name, fn):
        t = time.time()
        try:
            r = fn()
            steps.append({"op": name, "ok": True, "reply": r, "s": round(time.time() - t, 2)})
            print(f"[OK ] {name}: {r}", flush=True)
            return r
        except LinkError as e:
            steps.append({"op": name, "ok": False, "reply": f"{e.code}: {e}"})
            print(f"[FALLO] {name}: {e.code}: {e}", flush=True)
            raise

    try:
        step("Conectar", lambda: (link.open(), link.info().os_version)[1])
        root = step("Listar /", lambda: sorted(e.name for e in link.list("/")))
        if "TCM_TESTS" not in root:
            print("DETENIDO: /TCM_TESTS no existe (estado inesperado)")
            return 1
        existing = step("Listar /TCM_TESTS (antes)", lambda: sorted(e.name for e in link.list(TEST_DIR)))
        if posixpath.basename(remote) in existing:
            print("DETENIDO: el destino ya existe; no se sobrescribe")
            return 1
        step("Enviar", lambda: f"{link.put(local, remote)} bytes")
        listed = step("Listar /TCM_TESTS (después)",
                      lambda: {e.name: e.size for e in link.list(TEST_DIR)})
        if listed.get(posixpath.basename(remote)) != local.stat().st_size:
            print("DETENIDO: el tamaño listado no coincide")
            return 1
        back = out / (local.stem + ".descargado.tns")
        step("Descargar de nuevo", lambda: f"{link.get(remote, back)} bytes")
        same = sha(back) == sha(local)
        steps.append({"op": "SHA-256 enviado == descargado", "ok": same, "reply": sha(back)})
        print(f"[{'OK ' if same else 'FALLO'}] SHA-256 enviado == descargado: {sha(back)}")
        return 0 if same else 1
    except LinkError:
        return 1
    finally:
        link.close()
        report["upload"] = steps
        (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "prepare":
        r = prepare(Path(sys.argv[2]), Path(sys.argv[3]))
        print(json.dumps({k: v for k, v in r.items() if k != "diff"}, indent=2, ensure_ascii=False))
        print(r["diff"])
    elif len(sys.argv) == 3 and sys.argv[1] == "upload":
        raise SystemExit(upload(Path(sys.argv[2])))
    else:
        raise SystemExit(__doc__)
