"""Tests for the banjo CLI tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from banjo.cli import main, parse_progression_string


class TestParseProgressionString:
    def test_dash_separated(self):
        chords = parse_progression_string("ii7 - V7 - Imaj7")
        assert len(chords) == 3
        assert [c.numeral for c in chords] == ["ii7", "V7", "Imaj7"]
        assert all(c.duration_beats == 4.0 for c in chords)

    def test_comma_separated(self):
        chords = parse_progression_string("I, IV, V")
        assert [c.numeral for c in chords] == ["I", "IV", "V"]

    def test_space_separated(self):
        chords = parse_progression_string("i7 iv7 v7 i7")
        assert len(chords) == 4
        assert chords[0].numeral == "i7"

    def test_duration_colon_syntax(self):
        chords = parse_progression_string("ii7:2 - V7:2.5 - Imaj7:8")
        assert chords[0].duration_beats == 2.0
        assert chords[1].duration_beats == 2.5
        assert chords[2].duration_beats == 8.0

    def test_custom_defaults(self):
        chords = parse_progression_string(
            "I - V",
            default_beats=2.0,
            default_voicing="drop2",
            default_pattern="strum",
            default_rootless=True,
        )
        assert chords[0].duration_beats == 2.0
        assert chords[0].voicing == "drop2"
        assert chords[0].pattern == "strum"
        assert chords[0].rootless is True

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_progression_string("   ")

    def test_invalid_numeral_raises(self):
        with pytest.raises(ValueError, match="Invalid Roman numeral"):
            parse_progression_string("I - INVALID_CHORD - V")

    def test_invalid_duration_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_progression_string("I:notanumber - V")

    def test_zero_or_negative_duration_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_progression_string("I:0 - V")


class TestCliMain:
    def test_basic_generation(self, tmp_path: Path, capsys):
        exit_code = main(["ii7 - V7 - Imaj7", "--output-dir", str(tmp_path)])
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "Generated MIDI progression" in captured.out
        assert "C major" in captured.out
        assert "120 BPM" in captured.out

        mid_files = list(tmp_path.glob("*.mid"))
        md_files = list(tmp_path.glob("*.md"))
        assert len(mid_files) == 1
        assert len(md_files) == 1

    def test_custom_flags(self, tmp_path: Path, capsys):
        exit_code = main([
            "i - iv - V7",
            "--key", "A",
            "--mode", "minor",
            "--bpm", "90",
            "--pattern", "arpeggio_up",
            "--voicing", "drop2",
            "--voice-lead",
            "--filename", "test_custom_clip",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == 0

        mid_file = tmp_path / "test_custom_clip.mid"
        md_file = tmp_path / "test_custom_clip.md"
        assert mid_file.exists()
        assert md_file.exists()

        md_content = md_file.read_text()
        assert "A minor" in md_content
        assert "90 BPM" in md_content
        assert "arpeggio_up" in md_content

    def test_invalid_key_returns_error(self, capsys):
        exit_code = main(["I - V", "--key", "Z#"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_spread_plus_rootless_returns_error(self, capsys):
        exit_code = main(["I - V", "--voicing", "spread", "--rootless"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "rootless cannot be combined with voicing: spread" in captured.err
