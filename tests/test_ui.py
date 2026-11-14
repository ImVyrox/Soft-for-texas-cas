"""GUI smoke tests in demo mode (offscreen, no USB)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from texas_cas_manager.config import Settings  # noqa: E402
from texas_cas_manager.tns import container, lua  # noqa: E402


@pytest.fixture
def window(tmp_path, monkeypatch, qapp_wait):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from texas_cas_manager.ui.main_window import MainWindow
    win = MainWindow(Settings(workspace=str(tmp_path / "ws"), demo_mode=True))
    win.show()
    yield win
    win.editor.original_script = win.editor.code.toPlainText()  # no unsaved-changes prompt
    win.service.shutdown()
    win.close()


@pytest.fixture
def qapp_wait():
    from PySide6.QtCore import QCoreApplication, QElapsedTimer, QThreadPool
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def wait(cond, ms=5000):
        t = QElapsedTimer()
        t.start()
        while not cond() and t.elapsed() < ms:
            QCoreApplication.processEvents()
            QThreadPool.globalInstance().waitForDone(10)
        return cond()
    return wait


def test_demo_connects_lists_uploads_and_downloads(window, qapp_wait, tmp_path):
    assert qapp_wait(lambda: window.service.connected)
    assert qapp_wait(lambda: window.calc.remote.topLevelItemCount() == 2)
    doc = tmp_path / "ws" / "subido.tns"
    doc.write_bytes(lua.build_lua_document("print(1)\n"))
    window.calc.upload([str(doc)], "/")
    assert qapp_wait(lambda: "/subido.tns" in window.service.link.files)
    window.calc.download(["/demo.tns"], str(tmp_path / "ws"))
    assert qapp_wait(lambda: (tmp_path / "ws" / "demo.tns").exists())
    assert lua.read_script(container.parse((tmp_path / "ws" / "demo.tns").read_bytes())).startswith("--")


def test_editor_opens_edits_and_rebuilds(window, qapp_wait, tmp_path):
    src = tmp_path / "orig.tns"
    original = lua.build_lua_document("print('a')\n")
    src.write_bytes(original)
    window.open_document(str(src))
    assert qapp_wait(lambda: window.editor.editable)
    assert window.editor.code.toPlainText() == "print('a')\n"
    window.editor.code.setPlainText("print('b')\n")
    assert window.editor.dirty
    data = window.editor._rebuild()
    assert lua.read_script(container.parse(data)) == "print('b')\n"
    assert src.read_bytes() == original  # never modified


def test_all_pages_render(window, qapp_wait):
    for row in range(window.nav.count()):
        window.nav.setCurrentRow(row)
        qapp_wait(lambda: False, 50)
        assert window.stack.currentIndex() == row


def test_busy_listing_is_retried_and_reported(window, qapp_wait):
    from texas_cas_manager.core.link import ERR_BUSY, LinkError
    assert qapp_wait(lambda: window.service.connected)
    link = window.service.link
    real_list = link.list
    calls = {"n": 0}

    def flaky_list(folder):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LinkError("ocupada", ERR_BUSY)
        return real_list(folder)

    link.list = flaky_list
    window.calc.BUSY_DELAY_S = 0  # instance override: retry immediately in the test
    window.calc.refresh()
    assert qapp_wait(lambda: calls["n"] >= 2 and window.calc._busy_attempts == 0)
    assert window.calc.remote.topLevelItemCount() == 2
