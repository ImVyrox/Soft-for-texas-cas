"""Link client (against a fake helper and the mock), config helpers."""

import json
import stat
import sys
import textwrap

import pytest

from texas_cas_manager.config import Settings, atomic_write, unique_path
from texas_cas_manager.core.link import (ERR_BUSY, ERR_NOT_FOUND, ERR_TIMEOUT, HelperLink, LinkError, MockLink, check_remote_path,
                                         join)

FAKE = textwrap.dedent('''
    import json, sys
    files = {"/a.tns": b"AAAA", "/dir/b.tns": b"BB"}
    def out(o): print(json.dumps(o), flush=True)
    for line in sys.stdin:
        rid, cmd, *args = line.rstrip("\\n").split("\\t")
        if cmd == "quit": out({"id": rid, "ok": True}); break
        if cmd == "probe": out({"id": rid, "ok": True, "pids": [57362]}); continue
        if cmd in ("open", "resync", "close"): out({"id": rid, "ok": True}); continue
        if cmd == "info": out({"id": rid, "ok": True, "product_name": "TI-Nspire CX CAS", "os_version": "4.55.0079",
                               "flash_free": 10, "flash_total": 20, "ram_free": 1, "ram_total": 2, "battery_ok": True}); continue
        if cmd == "list" and args[0] == "/slow":
            sys.stderr.write("libticalcs: timeout" + chr(10)); sys.stderr.flush()
            out({"id": rid, "ok": False, "code": 9007, "error": "the calculator acknowledged the request but did not answer"}); continue
        if cmd == "list":
            items = [{"name": "a.tns", "size": 4, "type": 0}, {"name": "dir", "size": 0, "type": 1}] if args[0] == "/" else []
            out({"id": rid, "ok": True, "items": items}); continue
        if cmd == "get":
            if args[0] not in files: out({"id": rid, "ok": False, "code": 1010, "error": "the file or folder does not exist"}); continue
            out({"id": rid, "event": "progress", "done": 2, "total": 4})
            open(args[1], "wb").write(files[args[0]])
            out({"id": rid, "event": "progress", "done": 4, "total": 4})
            out({"id": rid, "ok": True, "size": len(files[args[0]])}); continue
        out({"id": rid, "ok": False, "code": 9001, "error": "unknown command"})
''')


@pytest.fixture
def fake_helper(tmp_path):
    p = tmp_path / "fake-helper"
    p.write_text(f"#!{sys.executable}\n" + FAKE)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    link = HelperLink(str(p), log_path=tmp_path / "helper.log")
    yield link
    link.close()


def test_helper_link_list_get_progress_and_errors(fake_helper, tmp_path):
    link = fake_helper
    assert link.probe() == [0xE012]
    link.open()
    assert link.is_open
    assert link.info().product_name == "TI-Nspire CX CAS"
    entries = link.list("/")
    assert [(e.path, e.is_dir) for e in entries] == [("/a.tns", False), ("/dir", True)]
    seen = []
    assert link.get("/a.tns", tmp_path / "a.tns", lambda d, t: seen.append((d, t))) == 4
    assert (tmp_path / "a.tns").read_bytes() == b"AAAA"
    assert seen == [(2, 4), (4, 4)]
    # Consecutive operations after a download keep working (one helper session).
    assert [e.name for e in link.list("/")] == ["a.tns", "dir"]
    with pytest.raises(LinkError) as exc:
        link.list("/slow")
    assert exc.value.code == ERR_BUSY and "ocupado" in str(exc.value)
    with pytest.raises(LinkError) as exc:
        link.get("/nope.tns", tmp_path / "x.tns")
    assert exc.value.code == ERR_NOT_FOUND and "no existe" in str(exc.value)
    link.close()
    assert not link.is_open
    assert "libticalcs: timeout" in (tmp_path / "helper.log").read_text()


def test_timeout_is_reported_not_retried(tmp_path):
    p = tmp_path / "slow"
    p.write_text(f"#!{sys.executable}\nimport json,sys\n"
                 "for l in sys.stdin:\n rid=l.split('\\t')[0]\n"
                 " print(json.dumps({'id':rid,'ok':False,'code':4,'error':'timeout'}),flush=True)\n")
    p.chmod(0o755)
    link = HelperLink(str(p))
    with pytest.raises(LinkError) as exc:
        link.list("/")
    assert exc.value.code == ERR_TIMEOUT
    link._proc.kill()


def test_missing_helper_gives_clear_error(monkeypatch):
    import texas_cas_manager.core.link as link_mod
    monkeypatch.setattr(link_mod, "find_helper", lambda: None)
    with pytest.raises(LinkError, match="tcm-link"):
        HelperLink().probe()


@pytest.mark.parametrize("bad", ["relative.tns", "/a\tb", "/a/../b.tns", "/x\n"])
def test_remote_path_validation(bad):
    with pytest.raises(LinkError):
        check_remote_path(bad)


def test_join():
    assert join("/", "a.tns") == "/a.tns"
    assert join("/dir", "b.tns") == "/dir/b.tns"


def test_mock_link_operations(tmp_path):
    m = MockLink({"/x/y/z.tns": b"123"})
    with pytest.raises(LinkError):
        m.list("/")  # not open
    m.open()
    assert [e.path for e in m.list("/")] == ["/x"]
    assert [e.path for e in m.list("/x")] == ["/x/y"]
    src = tmp_path / "n.tns"
    src.write_bytes(b"new")
    m.put(src, "/x/n.tns")
    m.rename("/x/n.tns", "/x/m.tns")
    m.get("/x/m.tns", tmp_path / "back.tns")
    assert (tmp_path / "back.tns").read_bytes() == b"new"
    m.delete("/x/m.tns")
    with pytest.raises(LinkError):
        m.rmdir("/x")  # not empty
    m.mkdir("/nuevo")
    m.rmdir("/nuevo")


def test_atomic_write_never_overwrites_by_default(tmp_path):
    f = tmp_path / "doc.tns"
    atomic_write(f, b"one")
    with pytest.raises(FileExistsError):
        atomic_write(f, b"two")
    assert f.read_bytes() == b"one"
    atomic_write(f, b"three", overwrite=True)
    assert f.read_bytes() == b"three"
    assert [p.name for p in tmp_path.iterdir()] == ["doc.tns"]  # no temp files left


def test_unique_path(tmp_path):
    f = tmp_path / "a.tns"
    assert unique_path(f) == f
    f.write_bytes(b"")
    assert unique_path(f).name == "a (2).tns"


def test_settings_roundtrip(tmp_path):
    s = Settings(theme="dark")
    for i in range(15):
        s.add_recent(f"/f{i}.tns")
    s.save(tmp_path / "s.json")
    loaded = Settings.load(tmp_path / "s.json")
    assert loaded.theme == "dark" and len(loaded.recent) == 10 and loaded.recent[0] == "/f14.tns"
    (tmp_path / "bad.json").write_text("{nope")
    assert Settings.load(tmp_path / "bad.json") == Settings()
    assert json.loads((tmp_path / "s.json").read_text())["theme"] == "dark"
