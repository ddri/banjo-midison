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


def test_generate_minimal_args(isolated_config_dir, tmp_path):
    """Minimal valid args produce a MIDI file in the configured output dir."""
    out = tmp_path / "out"
    config.set_output_directory(out)

    result = mcp_server.handle_generate_midi_progression({
        "key_center": "C",
        "scale_type": "major",
        "bpm": 110,
        "chords": [
            {"numeral": "ii7", "duration_beats": 4},
            {"numeral": "V7", "duration_beats": 4},
            {"numeral": "Imaj7", "duration_beats": 8},
        ],
    })

    assert "filepath" in result
    assert "sidecar_path" in result
    assert "resolved" in result
    assert "total_beats" in result
    assert result["total_beats"] == 16
    assert Path(result["filepath"]).exists()
    assert Path(result["filepath"]).suffix == ".mid"
    assert Path(result["sidecar_path"]).exists()
    assert Path(result["sidecar_path"]).suffix == ".md"
    # Resolved metadata is a list of per-chord dicts.
    assert len(result["resolved"]) == 3
    assert result["resolved"][0]["numeral"] == "ii7"
    assert result["resolved"][0]["voicing"] == "close"  # default applied
