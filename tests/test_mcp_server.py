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


def test_generate_full_args(isolated_config_dir, tmp_path):
    """All 11 fields exercised, with humanization, secondary dominant, alterations."""
    out = tmp_path / "out"
    config.set_output_directory(out)

    result = mcp_server.handle_generate_midi_progression({
        "key_center": "Eb",
        "scale_type": "major",
        "bpm": 72,
        "chords": [
            {"numeral": "Imaj9", "duration_beats": 4, "voicing": "drop2"},
            {"numeral": "V7/vi", "duration_beats": 2, "voicing": "drop2"},
            {"numeral": "vi9",   "duration_beats": 4, "voicing": "drop2"},
            {"numeral": "ii9",   "duration_beats": 2, "voicing": "drop2"},
            {"numeral": "V13",   "duration_beats": 2, "voicing": "drop2"},
            {"numeral": "Imaj9", "duration_beats": 2, "voicing": "drop2", "inversion": 1},
        ],
        "octave": 4,
        "time_signature": "4/4",
        "humanize": {"velocity_range": 10, "timing_ms": 6, "base_velocity": 75},
        "seed": 7,
        "filename": "neo_soul_test",
        "prompt_context": "Neo-soul in Eb with secondary dominant approach to vi.",
        "generation_notes": "Drop-2 voicings throughout for a slightly horn-like spread.",
    })

    midi_path = Path(result["filepath"])
    assert midi_path.name == "neo_soul_test.mid"
    assert midi_path.exists()
    assert midi_path.parent == out.resolve()

    # Sidecar contains the prompt context and generation notes.
    sidecar_text = Path(result["sidecar_path"]).read_text()
    assert "Neo-soul in Eb" in sidecar_text
    assert "Drop-2 voicings" in sidecar_text
    assert "Seed: 7" in sidecar_text

    assert result["total_beats"] == 16
    assert len(result["resolved"]) == 6
    # Inversion override on the last chord made it through.
    assert result["resolved"][-1]["inversion"] == 1


def test_generate_missing_required_raises():
    with pytest.raises(ValueError, match="Missing required argument: key_center"):
        mcp_server.handle_generate_midi_progression({
            "scale_type": "major", "bpm": 100, "chords": [{"numeral": "I", "duration_beats": 4}],
        })


def test_generate_empty_chords_raises():
    with pytest.raises(ValueError, match="non-empty list"):
        mcp_server.handle_generate_midi_progression({
            "key_center": "C", "scale_type": "major", "bpm": 100, "chords": [],
        })


def test_generate_chord_missing_fields_raises():
    with pytest.raises(ValueError, match="numeral.*duration_beats"):
        mcp_server.handle_generate_midi_progression({
            "key_center": "C", "scale_type": "major", "bpm": 100,
            "chords": [{"numeral": "I"}],  # missing duration_beats
        })


def test_generate_bad_numeral_raises():
    """Parser errors propagate cleanly to MCP."""
    with pytest.raises(ValueError):  # parse_roman_numeral raises ValueError
        mcp_server.handle_generate_midi_progression({
            "key_center": "C", "scale_type": "major", "bpm": 100,
            "chords": [{"numeral": "ZZZZ", "duration_beats": 4}],
        })


def test_generate_bad_scale_raises():
    with pytest.raises(ValueError, match="Unknown mode"):
        mcp_server.handle_generate_midi_progression({
            "key_center": "C", "scale_type": "bogolian", "bpm": 100,
            "chords": [{"numeral": "I", "duration_beats": 4}],
        })


def test_generate_creates_default_output_dir(isolated_config_dir, tmp_path, monkeypatch):
    """When no config is set, falls back to DEFAULT_OUTPUT_DIR (created on first write)."""
    # isolated_config_dir fixture already redirects DEFAULT_OUTPUT_DIR into tmp_path.
    default_out = tmp_path / "Music" / "banjo"
    assert not default_out.exists()

    result = mcp_server.handle_generate_midi_progression({
        "key_center": "G", "scale_type": "major", "bpm": 90,
        "chords": [{"numeral": "I", "duration_beats": 4}],
    })

    assert default_out.is_dir()
    assert Path(result["filepath"]).parent == default_out.resolve()
