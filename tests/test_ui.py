"""GUI smoke tests in demo mode (offscreen, no USB)."""

import os
from pathlib import Path

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
    win.editor.discard_changes()  # no unsaved-changes prompt
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


def test_editor_tabs_native_document_explorer_and_safe_save(window, qapp_wait, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from native_fixture import SCRIPT, native_document
    src = tmp_path / "nativo.tns"
    original = native_document()
    src.write_bytes(original)
    window.open_document(str(src))
    ed = window.editor
    assert qapp_wait(lambda: ed.tab is not None and ed.tab.report is not None)
    tab = ed.tab
    roots = {tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())}
    assert roots == {"Scripts (1)", "XML (2)", "Recursos (1)", "Secciones binarias (3)"}
    assert tab.code.toPlainText() == SCRIPT and not tab.code.isReadOnly()
    # XML viewer shows the decoded XML; resources are listed
    xml_root = next(tab.tree.topLevelItem(i) for i in range(4) if tab.tree.topLevelItem(i).text(0).startswith("XML"))
    tab.tree.setCurrentItem(xml_root.child(0))
    assert "<doc ver=" in tab.xml_view.toPlainText() and tab.stack.currentWidget() is tab.xml_view
    # edit the script, rebuild, save as new file: original untouched
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    tab.code.setPlainText("-- nuevo\n")
    assert tab.dirty and ed.tabs.tabText(ed.tabs.currentIndex()).endswith("*")
    data = tab.build()
    assert ed.write_version(tab, data, src) is False  # refuses the original
    out = tmp_path / "nativo (editado).tns"
    assert ed.write_version(tab, data, out)
    assert src.read_bytes() == original
    from texas_cas_manager.tns import lua
    assert lua.read_script(container.parse(out.read_bytes())) == "-- nuevo\n"
    # a second document opens in its own tab
    ed.new_document()
    assert ed.tabs.count() == 2 and ed.tab.is_new


def test_protected_script_opens_read_only(window, qapp_wait, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from native_fixture import native_document
    src = tmp_path / "protegido.tns"
    src.write_bytes(native_document(cry="1"))
    window.open_document(str(src))
    ed = window.editor
    assert qapp_wait(lambda: ed.tab is not None and ed.tab.report is not None)
    assert ed.tab.code.isReadOnly() and not ed.editable
    assert not ed.act_rebuild.isEnabled() and "editables" in ed.act_rebuild.toolTip()


def test_find_replace_and_autoindent(window):
    from texas_cas_manager.ui.widgets.code_editor import CodeEditor
    from texas_cas_manager.ui.widgets.find_bar import FindBar
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    ed = CodeEditor()
    ed.setPlainText("a = 1\nb = a + a\n")
    bar = FindBar()
    bar.attach(ed)
    bar.find.setText("a")
    bar.replace.setText("x")
    bar.replace_all()
    assert ed.toPlainText() == "x = 1\nb = x + x\n"
    ed.undo()
    assert ed.toPlainText() == "a = 1\nb = a + a\n"  # one undo step
    ed.setPlainText("if x then")
    c = ed.textCursor()
    c.movePosition(c.MoveOperation.End)
    ed.setTextCursor(c)
    QTest.keyClick(ed, Qt.Key_Return)
    assert ed.toPlainText() == "if x then\n  "
