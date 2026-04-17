"""Tests for ~/.banjo/config.json read/write helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from banjo import config


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR to a tmp path so tests don't touch ~/.banjo/."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".banjo")
    return tmp_path / ".banjo"


def test_default_output_directory_when_no_config(isolated_config_dir):
    # No config file exists yet.
    assert not (isolated_config_dir / "config.json").exists()
    result = config.get_output_directory()
    assert result == Path.home() / "Music" / "banjo"


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
    returned = config.set_output_directory("~/banjo_test_xyz")
    assert returned == (Path.home() / "banjo_test_xyz").resolve()
    assert "~" not in str(returned)


def test_get_output_directory_handles_corrupt_config(isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "config.json").write_text("not valid json {{{")
    # Should silently fall back to default rather than crash.
    assert config.get_output_directory() == Path.home() / "Music" / "banjo"
