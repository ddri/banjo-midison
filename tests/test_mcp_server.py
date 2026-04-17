# tests/test_mcp_server.py
"""Tests for MCP tool handlers (pure functions on dicts, no transport involved)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from banjo import config, mcp_server


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Redirect both CONFIG_DIR and the default output dir to tmp."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".banjo")
    monkeypatch.setattr(config, "DEFAULT_OUTPUT_DIR", tmp_path / "Music" / "banjo")
    return tmp_path


def test_set_output_directory_handler_persists(tmp_path):
    target = tmp_path / "studio"
    result = mcp_server.handle_set_output_directory({"path": str(target)})
    assert result == {"output_directory": str(target.resolve())}
    assert config.get_output_directory() == target.resolve()


def test_set_output_directory_missing_path_raises():
    with pytest.raises(ValueError, match="path"):
        mcp_server.handle_set_output_directory({})


def test_set_output_directory_non_string_raises():
    with pytest.raises(ValueError, match="string"):
        mcp_server.handle_set_output_directory({"path": 42})


def test_set_output_directory_empty_string_raises():
    with pytest.raises(ValueError, match="empty"):
        mcp_server.handle_set_output_directory({"path": ""})
