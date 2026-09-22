"""Tests for the banjo CLI tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from midison.cli import main, parse_progression_string


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

    def test_miditool_dict_flag(self, capsys):
        exit_code = main(["ii7 - V7 - Imaj7", "--miditool-dict"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert '"notes": [' in captured.out
        assert '"pitch":' in captured.out

    def test_install_ableton_osc_flag(self, capsys, monkeypatch):
        from unittest.mock import patch
        with patch("midison.cli.install_ableton_osc", return_value=Path("/mock/AbletonOSC")):
            exit_code = main(["--install-ableton-osc"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Installed AbletonOSC successfully" in captured.out

    def test_install_m4l_flag(self, capsys):
        from unittest.mock import patch
        with patch("midison.cli.install_m4l_device", return_value=Path("/mock/Midison Generator.amxd")):
            exit_code = main(["--install-m4l"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Installed Midison Generator.amxd successfully" in captured.out

    def test_to_ableton_flag_offline(self, capsys, tmp_path):
        from unittest.mock import MagicMock, patch
        from midison.ableton import AbletonSessionState

        mock_client = MagicMock()
        mock_client.query_session_state.return_value = AbletonSessionState(connected=False)
        mock_client.inject_progression.return_value = {
            "status": "success", "track_index": 0, "clip_index": 0,
            "total_beats": 4.0, "notes_count": 8, "fired": True,
        }
        with patch("midison.cli.AbletonClient", return_value=mock_client):
            exit_code = main(["ii7 - V7", "--to-ableton", "--output-dir", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "session sync offline" in captured.out
        assert "Injected directly into Ableton Live" in captured.out
        assert "Track:        Track 1 (idx 0)" in captured.out

    def test_to_ableton_flag_online_sync(self, capsys, tmp_path):
        from unittest.mock import MagicMock, patch
        from midison.ableton import AbletonSessionState

        mock_client = MagicMock()
        mock_client.query_session_state.return_value = AbletonSessionState(
            connected=True,
            tempo=126.0,
            signature_numerator=4,
            signature_denominator=4,
            selected_track=2,
            selected_scene=1,
            root_note=0,
            scale_name="Major",
        )
        mock_client.inject_progression.return_value = {
            "status": "success", "track_index": 2, "clip_index": 1,
            "total_beats": 4.0, "notes_count": 8, "fired": True,
        }
        with patch("midison.cli.AbletonClient", return_value=mock_client):
            exit_code = main(["ii7 - V7", "--to-ableton", "--output-dir", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "⚡ Synced with Ableton Live: 126.0 BPM (4/4)" in captured.out
        assert "Target: Track 3 (idx 2), Clip Slot 2 (idx 1)" in captured.out
        assert "Track:        Track 3 (idx 2)" in captured.out
        mock_client.inject_progression.assert_called_once()
        call_args = mock_client.inject_progression.call_args
        assert call_args.kwargs["track_index"] == 2
        assert call_args.kwargs["clip_index"] == 1
        req = call_args.args[0]
        assert req.bpm == 126

    def test_to_ableton_flag_user_override(self, capsys, tmp_path):
        from unittest.mock import MagicMock, patch
        from midison.ableton import AbletonSessionState

        mock_client = MagicMock()
        mock_client.query_session_state.return_value = AbletonSessionState(
            connected=True,
            tempo=126.0,
            selected_track=0,
            selected_scene=0,
        )
        mock_client.inject_progression.return_value = {
            "status": "success", "track_index": 5, "clip_index": 3,
            "total_beats": 4.0, "notes_count": 8, "fired": True,
        }
        with patch("midison.cli.AbletonClient", return_value=mock_client):
            exit_code = main([
                "ii7 - V7", "--to-ableton", "-b", "145", "--track", "5", "--clip", "3",
                "--output-dir", str(tmp_path)
            ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Target: Track 6 (idx 5), Clip Slot 4 (idx 3)" in captured.out
        call_args = mock_client.inject_progression.call_args
        assert call_args.kwargs["track_index"] == 5
        assert call_args.kwargs["clip_index"] == 3
        req = call_args.args[0]
        assert req.bpm == 145

    def test_play_stream_flag(self, capsys, tmp_path):
        from unittest.mock import patch
        with patch("midison.cli.stream_progression") as mock_stream:
            exit_code = main(["ii7 - V7", "--play", "--output-dir", str(tmp_path)])
        assert exit_code == 0
        mock_stream.assert_called_once()
        captured = capsys.readouterr()
        assert "Streaming live to MIDI port" in captured.out
