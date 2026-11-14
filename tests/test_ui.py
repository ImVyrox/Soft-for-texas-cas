"""GUI smoke tests in demo mode (offscreen, no USB)."""

import os
from pathlib import Path

from PySide6.QtCore import Qt

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
    assert roots == {"Páginas (2)", "Scripts (1)", "XML (2)", "Recursos (1)", "Secciones binarias (3)"}
    assert tab.code.toPlainText() == SCRIPT and not tab.code.isReadOnly()
    # XML viewer shows the decoded XML; resources are listed
    xml_root = section(tab, "XML")
    tab.tree.setCurrentItem(xml_root.child(0))
    assert "<doc ver=" in tab.xml_view.toPlainText() and tab.stack.currentWidget() is tab.xml_view
    # edit the script, rebuild, save as new file: original untouched
    tab.tree.setCurrentItem(section(tab, "Scripts").child(0))
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



def section(tab, prefix):
    return next(tab.tree.topLevelItem(i) for i in range(tab.tree.topLevelItemCount())
                if tab.tree.topLevelItem(i).text(0).startswith(prefix))


def test_notes_pages_edit_status_and_history(window, qapp_wait, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from native_fixture import MATH_BOX, notes_document, word
    from texas_cas_manager.tns import notes
    src = tmp_path / "notas.tns"
    original = notes_document([[word("uno"), word("abc") + MATH_BOX + word(""), word("tres")], [word("x")]])
    src.write_bytes(original)
    window.open_document(str(src))
    ed = window.editor
    assert qapp_wait(lambda: ed.tab is not None and ed.tab.report is not None)
    tab = ed.tab
    pages = section(tab, "Páginas")
    assert pages.childCount() == 2 and pages.child(0).text(0).endswith("[editable]")
    tab.tree.setCurrentItem(pages.child(0))
    view, t = tab.page_view, tab.page_table
    assert tab.stack.currentWidget() is view

    def rows():
        return [(t.item(r, 0).text(), t.item(r, 1).text(), t.item(r, 2).text()) for r in range(t.rowCount())]
    assert rows() == [("Párrafo", "uno", "editable"), ("Párrafo con objetos", "", "solo lectura"),
                      ("   ↳ Texto", "abc", "editable"), ("   ↳ Matemáticas", "2+3  →  5", "solo lectura"),
                      ("Párrafo", "tres", "editable")]
    assert "caché" in t.item(3, 2).toolTip()
    # edit a run inside the complex paragraph, and a whole text paragraph
    t.item(2, 1).setText("ABC ñ")
    t.item(0, 1).setText("UNO")
    t.item(4, 1).setText("a<b")  # rejected and restored
    assert t.item(4, 1).text() == "tres"
    # structural: insert after "tres", move it up, delete it
    t.selectRow(4)
    assert view.btn_insert.isEnabled() and view.btn_delete.isEnabled()
    view.btn_insert.click()
    assert [r[1] for r in rows()][-1] == "" and t.rowCount() == 6
    t.item(5, 1).setText("nuevo")
    t.selectRow(1)  # complex paragraph: cannot be deleted
    assert not view.btn_delete.isEnabled() and "objetos" in view.btn_delete.toolTip()
    assert view.btn_delete.accessibleName() == "Eliminar párrafo"
    t.selectRow(5)
    view.btn_up.click()
    assert [r[1] for r in rows() if r[0] == "Párrafo"] == ["UNO", "nuevo", "tres"]
    # undo / redo through the editor toolbar
    ed.undo()
    assert [r[1] for r in rows() if r[0] == "Párrafo"] == ["UNO", "tres", "nuevo"]
    ed.redo()
    assert [r[1] for r in rows() if r[0] == "Párrafo"] == ["UNO", "nuevo", "tres"]
    # move the page
    view.btn_page_down.click()
    assert tab.state.orders == {"Problem1.xml": [1, 0]} and "→ 2" in pages.child(0).text(0)
    assert tab.dirty
    data = tab.build()
    out = notes.document_pages(container.parse(data))
    assert [r.text for r in out[0].runs] == ["x"]  # pages swapped
    assert [r.text for r in out[1].runs][:5] == ["UNO", "ABC ñ", "", "nuevo", "tres"] and out[1].math[0].input == "2+3"
    assert src.read_bytes() == original
    history = [tab.history.item(i).text() for i in range(tab.history.count())]
    assert any("Párrafo insertado" in h for h in history) and any("Deshecho" in h for h in history)


def test_other_page_types_are_read_only(window, qapp_wait, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from native_fixture import multi_page_xml, encrypted_entry, DOCUMENT_XML
    data = container.write(container.TnsDocument("0601", [encrypted_entry("Document.xml", DOCUMENT_XML),
                                                          encrypted_entry("Problem1.xml", multi_page_xml())]))
    src = tmp_path / "paginas.tns"
    src.write_bytes(data)
    window.open_document(str(src))
    ed = window.editor
    assert qapp_wait(lambda: ed.tab is not None and ed.tab.report is not None)
    tab = ed.tab
    pages = section(tab, "Páginas")
    labels = [pages.child(i).text(0) for i in range(pages.childCount())]
    assert labels[1].startswith("Pág. 2 · Calculadora") and labels[1].endswith("[solo lectura]")
    tab.tree.setCurrentItem(pages.child(1))
    t = tab.page_table
    assert (t.item(0, 0).text(), t.item(0, 1).text()) == ("Entrada", "2+3  →  5")
    assert not t.item(0, 1).flags() & Qt.ItemIsEditable
    assert not tab.page_view.btn_insert.isEnabled() and "notas" in tab.page_view.btn_insert.toolTip()
    assert "f1(x)=x^2" in tab.props.toPlainText()


def test_function_navigation_and_folding(window):
    from texas_cas_manager.ui.widgets.code_editor import CodeEditor
    ed = CodeEditor()
    ed.setPlainText("function a()\n  return 1\nend\nfunction b()\n  if x then\n    y()\n  end\nend\n")
    ed._update_regions()
    assert ed.fold_regions() == {1: 3, 4: 8, 5: 7}
    ed.toggle_fold(4)
    assert not ed.is_line_visible(5) and not ed.is_line_visible(7) and ed.is_line_visible(8)
    ed.toggle_fold(4)
    assert ed.is_line_visible(6)
    ed.toggle_fold(1)
    ed.go_to_line(2)  # navigating into a folded block unfolds it
    assert ed.is_line_visible(2) and ed.textCursor().blockNumber() == 1


def test_regex_and_whole_word_search(window):
    from texas_cas_manager.ui.widgets.code_editor import CodeEditor
    from texas_cas_manager.ui.widgets.find_bar import FindBar
    ed = CodeEditor()
    ed.setPlainText("x = x1 + x\nfoo(12) foo(345)\n")
    bar = FindBar()
    bar.attach(ed)
    bar.find.setText("x")
    bar.whole.setChecked(True)
    bar.replace.setText("y")
    bar.replace_all()
    assert ed.toPlainText().startswith("y = x1 + y")
    bar.whole.setChecked(False)
    bar.regex.setChecked(True)
    bar.find.setText(r"foo\((\d+)\)")
    bar.replace.setText(r"bar(\1)")
    bar.replace_all()
    assert "bar(12) bar(345)" in ed.toPlainText()
    bar.find.setText("(")
    bar.replace_all()
    assert bar.status.text() == "Regex no válida"
