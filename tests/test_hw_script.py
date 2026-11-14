"""The guarded hardware write test: path guard and a full run on the mock."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hwtest", ROOT / "scripts" / "hardware_write_test.py")
hwtest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hwtest)


@pytest.mark.parametrize("path", ["/Ejemplos/P2.tns", "/TCM_TESTS", "/TCM_TESTS/../potenciales.tns",
                                  "/TCM_TESTS/sub/x.tns", "/TCM_TESTSX/a.tns", "TCM_TESTS/a.tns", "/a.tns"])
def test_guard_rejects_paths_outside_test_dir(path):
    with pytest.raises(hwtest.Abort):
        hwtest.assert_in_test_dir(path)


def test_guard_accepts_test_files():
    hwtest.assert_in_test_dir("/TCM_TESTS/tcm_prueba.tns")
    hwtest.assert_in_test_dir("/TCM_TESTS", allow_dir_itself=True)


def test_full_sequence_on_mock(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "hardware_write_test.py"), str(tmp_path), "--mock"],
                       capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FALLO" not in r.stdout and "9. Verificar eliminación" in r.stdout
