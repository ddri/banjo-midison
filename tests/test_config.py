"""Tests for ~/.midison/config.json read/write helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from midison import config


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR to a tmp path so tests don't touch ~/.midison/."""
    cfg_dir = tmp_path / ".midison"
    legacy_dir = tmp_path / ".banjo"
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "LEGACY_CONFIG_DIR", legacy_dir)
    monkeypatch.setattr(config, "DEFAULT_OUTPUT_DIR", tmp_path / "Music" / "midison")
    monkeypatch.setattr(config, "LEGACY_OUTPUT_DIR", tmp_path / "Music" / "banjo")
    return cfg_dir


def test_default_output_directory_when_no_config(isolated_config_dir, tmp_path):
    # No config file exists yet.
    assert not (isolated_config_dir / "config.json").exists()
    result = config.get_output_directory()
    assert result == tmp_path / "Music" / "midison"


def test_legacy_output_directory_fallback_when_banjo_exists(isolated_config_dir, tmp_path):
    legacy_out = tmp_path / "Music" / "banjo"
    legacy_out.mkdir(parents=True)
    result = config.get_output_directory()
    assert result == legacy_out


def test_set_output_directory_persists(isolated_config_dir, tmp_path):
    target = tmp_path / "studio_output"
    returned = config.set_output_directory(target)
    assert returned == target.resolve()

    # Persisted on disk.
    cfg_file = isolated_config_dir / "config.json"
    assert cfg_file.exists()
    data = json.loads(cfg_file.read_text())
    assert data["output_directory"] == str(target.resolve())

    # Subsequent get returns the same value.
    assert config.get_output_directory() == target.resolve()


def test_set_output_directory_creates_config_dir(isolated_config_dir, tmp_path):
    assert not isolated_config_dir.exists()
    config.set_output_directory(tmp_path / "out")
    assert isolated_config_dir.is_dir()


def test_set_output_directory_expands_tilde(isolated_config_dir):
    returned = config.set_output_directory("~/midison_test_xyz")
    assert returned == (Path.home() / "midison_test_xyz").resolve()
    assert "~" not in str(returned)


def test_get_output_directory_handles_corrupt_config(isolated_config_dir, tmp_path):
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "config.json").write_text("not valid json {{{")
    # Should silently fall back to default rather than crash.
    assert config.get_output_directory() == tmp_path / "Music" / "midison"
