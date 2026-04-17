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
