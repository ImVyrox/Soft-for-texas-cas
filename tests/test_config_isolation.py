"""Regression: tests once wrote a pytest tmp path into the user's real settings."""

from pathlib import Path

from texas_cas_manager.config import Settings, config_dir


def test_settings_follow_xdg_config_home_set_after_import(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "other"))
    Settings(workspace="/x").save()
    assert (tmp_path / "other" / "texas-cas-manager" / "settings.json").is_file()
    assert config_dir() == tmp_path / "other" / "texas-cas-manager"


def test_default_workspace_is_in_home_documents():
    assert Path(Settings().workspace) == Path.home() / "Documentos" / "TI-Nspire"
