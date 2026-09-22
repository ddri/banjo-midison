"""
Unit tests for Ableton Live direct clip injection (banjo.ableton).
"""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from midison.ableton import (
    AbletonClient,
    find_ableton_remote_scripts_dir,
    install_ableton_osc,
)
from midison.events import TimedNote
from midison.midi_writer import ChordSpec, GenerationRequest


def test_ableton_client_sends_create_clip():
    mock_udp = MagicMock()
    with patch("pythonosc.udp_client.SimpleUDPClient", return_value=mock_udp):
        client = AbletonClient()
        client.create_clip(track_index=1, clip_index=2, length_beats=8.0)

    mock_udp.send_message.assert_called_once_with(
        "/live/clip_slot/create_clip", [1, 2, 8.0]
    )


def test_ableton_client_sends_add_note():
    mock_udp = MagicMock()
    with patch("pythonosc.udp_client.SimpleUDPClient", return_value=mock_udp):
        client = AbletonClient()
        client.add_note(
            track_index=0,
            clip_index=0,
            pitch=60,
            start_time=1.5,
            duration=0.5,
            velocity=95,
            mute=False,
        )

    mock_udp.send_message.assert_called_once_with(
        "/live/clip/add/notes", [0, 0, 60, 1.5, 0.5, 95, 0]
    )


def test_ableton_client_fire_and_stop_clip():
    mock_udp = MagicMock()
    with patch("pythonosc.udp_client.SimpleUDPClient", return_value=mock_udp):
        client = AbletonClient()
        client.fire_clip(0, 1)
        client.stop_clip(0, 1)

    assert mock_udp.send_message.call_count == 2
    assert mock_udp.send_message.call_args_list[0][0] == ("/live/clip/fire", [0, 1])
    assert mock_udp.send_message.call_args_list[1][0] == ("/live/clip/stop", [0, 1])


def test_ableton_client_inject_progression():
    mock_udp = MagicMock()
    req = GenerationRequest(
        key_center="Eb",
        scale_type="major",
        bpm=120,
        chords=[ChordSpec(numeral="ii7", duration_beats=2.0)],
    )

    with patch("pythonosc.udp_client.SimpleUDPClient", return_value=mock_udp):
        client = AbletonClient()
        res = client.inject_progression(req, track_index=2, clip_index=3, fire=True)

    assert res["status"] == "success"
    assert res["track_index"] == 2
    assert res["clip_index"] == 3
    assert res["total_beats"] == 2.0
    assert res["notes_count"] == 4  # 4 notes in ii7

    # Calls: 1 create_clip + 4 add_notes + 1 fire_clip = 6 messages
    assert mock_udp.send_message.call_count == 6


def test_find_ableton_remote_scripts_dir():
    scripts_dir = find_ableton_remote_scripts_dir()
    assert isinstance(scripts_dir, Path)
    assert scripts_dir.name == "Remote Scripts"


def test_install_ableton_osc_custom_dir(tmp_path):
    target = tmp_path / "custom_scripts" / "AbletonOSC"
    with patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0)
        res = install_ableton_osc(target)

    assert res == target
    mock_subproc.assert_called_once()
    assert "clone" in mock_subproc.call_args[0][0]
