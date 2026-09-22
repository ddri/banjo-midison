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


def test_ableton_session_state_properties():
    from midison.ableton import AbletonSessionState

    state = AbletonSessionState(
        tempo=135.0,
        signature_numerator=6,
        signature_denominator=8,
        selected_track=3,
        selected_scene=2,
        root_note=0,  # C
        scale_name="Major",
        connected=True,
    )
    assert state.time_signature == "6/8"
    assert state.key_name == "C"

    state2 = AbletonSessionState(root_note=9, scale_name="Minor")
    assert state2.key_name == "A"

    state_none = AbletonSessionState(root_note=None)
    assert state_none.key_name is None


def test_query_session_state_success():
    import socket
    from pythonosc.osc_message_builder import OscMessageBuilder
    from midison.ableton import AbletonClient

    def make_dgram(address, *args):
        b = OscMessageBuilder(address=address)
        for a in args:
            b.add_arg(a)
        return b.build().dgram

    packets = [
        (make_dgram("/live/song/get/tempo", 128.0), ("127.0.0.1", 11000)),
        (make_dgram("/live/song/get/signature_numerator", 4), ("127.0.0.1", 11000)),
        (make_dgram("/live/song/get/signature_denominator", 4), ("127.0.0.1", 11000)),
        (make_dgram("/live/view/get/selected_track", 2), ("127.0.0.1", 11000)),
        (make_dgram("/live/view/get/selected_scene", 3), ("127.0.0.1", 11000)),
        (make_dgram("/live/song/get/root_note", 2), ("127.0.0.1", 11000)),  # D
        (make_dgram("/live/song/get/scale_name", "Dorian"), ("127.0.0.1", 11000)),
    ]

    mock_sock = MagicMock()
    # Return packets in order, then raise socket.timeout
    mock_sock.recvfrom.side_effect = list(packets) + [socket.timeout("timed out")]

    client = AbletonClient()
    with patch.object(client, "_create_receive_socket", return_value=mock_sock):
        state = client.query_session_state(timeout=0.1)

    assert state.connected is True
    assert state.tempo == 128.0
    assert state.signature_numerator == 4
    assert state.signature_denominator == 4
    assert state.time_signature == "4/4"
    assert state.selected_track == 2
    assert state.selected_scene == 3
    assert state.root_note == 2
    assert state.key_name == "D"
    assert state.scale_name == "Dorian"


def test_query_session_state_offline_fallback():
    from midison.ableton import AbletonClient

    mock_sock = MagicMock()
    import socket
    mock_sock.recvfrom.side_effect = socket.timeout("timed out")

    client = AbletonClient()
    with patch.object(client, "_create_receive_socket", return_value=mock_sock):
        state = client.query_session_state(timeout=0.05)

    assert state.connected is False
    assert state.tempo == 120.0
    assert state.selected_track == 0
    assert state.selected_scene == 0


def test_query_session_state_socket_bind_error():
    from midison.ableton import AbletonClient

    client = AbletonClient()
    with patch.object(client, "_create_receive_socket", return_value=None):
        state = client.query_session_state(timeout=0.05)

    assert state.connected is False
    assert state.tempo == 120.0


def test_is_connected():
    from midison.ableton import AbletonClient, AbletonSessionState

    client = AbletonClient()
    with patch.object(client, "query_session_state") as mock_query:
        mock_query.return_value = AbletonSessionState(connected=True)
        assert client.is_connected() is True

        mock_query.return_value = AbletonSessionState(connected=False)
        assert client.is_connected() is False


def test_inject_progression_auto_sync():
    from midison.ableton import AbletonClient, AbletonSessionState

    client = AbletonClient()
    req = GenerationRequest(
        key_center="C",
        scale_type="major",
        bpm=120,
        chords=[ChordSpec(numeral="I", duration_beats=4.0)],
    )

    mock_session = AbletonSessionState(
        connected=True,
        selected_track=3,
        selected_scene=5,
    )
    with patch.object(client, "query_session_state", return_value=mock_session), \
         patch.object(client, "create_clip") as mock_create, \
         patch.object(client, "add_notes") as mock_add, \
         patch.object(client, "fire_clip") as mock_fire:

        res = client.inject_progression(req, track_index=None, clip_index=None, fire=True)

    assert res["status"] == "success"
    assert res["track_index"] == 3
    assert res["clip_index"] == 5
    assert res["session_synced"] is True
    mock_create.assert_called_once_with(3, 5, 4.0)
    mock_fire.assert_called_once_with(3, 5)

