"""
Unit tests for real-time virtual MIDI streaming (banjo.stream).
"""

import threading
import time
from unittest.mock import MagicMock, patch

import mido
import pytest

from banjo.events import TimedNote
from banjo.midi_writer import ChordSpec, GenerationRequest
from banjo.stream import (
    get_available_output_ports,
    open_midi_output,
    stop_all_notes,
    stream_notes,
    stream_progression,
)


def test_get_available_output_ports():
    ports = get_available_output_ports()
    assert isinstance(ports, list)


def test_stop_all_notes_sends_panic_messages():
    mock_port = MagicMock()
    stop_all_notes(mock_port, channel=0)

    # Should send CC 123 (all notes off), CC 120 (all sound off), plus note_offs
    sent_types = [call[0][0].type for call in mock_port.send.call_args_list]
    assert "control_change" in sent_types
    assert "note_off" in sent_types


def test_stream_notes_dispatches_on_and_off_events():
    mock_port = MagicMock()
    notes = [
        TimedNote(pitch=60, start_beat=0.0, duration_beats=0.1, velocity=90),
        TimedNote(pitch=64, start_beat=0.0, duration_beats=0.1, velocity=85),
    ]

    # Use very fast BPM so test executes instantaneously
    sent_count = stream_notes(
        notes=notes,
        bpm=6000,  # ultra fast for unit test
        total_beats=0.2,
        port=mock_port,
        loop=False,
    )

    # 2 notes = 2 on + 2 off = 4 messages
    assert sent_count == 4
    # Failsafe panic messages sent at exit
    assert mock_port.send.call_count >= 4

    messages = [call[0][0] for call in mock_port.send.call_args_list[:4]]
    assert messages[0].type == "note_on"
    assert messages[0].note in (60, 64)


def test_stream_notes_with_stop_event():
    mock_port = MagicMock()
    notes = [
        TimedNote(pitch=60, start_beat=0.0, duration_beats=1.0, velocity=80),
    ]

    stop_event = threading.Event()
    stop_event.set()  # Stop immediately

    sent_count = stream_notes(
        notes=notes,
        bpm=120,
        port=mock_port,
        loop=True,
        stop_event=stop_event,
    )
    assert sent_count == 0


def test_stream_progression_resolves_and_plays():
    mock_port = MagicMock()
    req = GenerationRequest(
        key_center="C",
        scale_type="major",
        bpm=6000,
        chords=[ChordSpec(numeral="I", duration_beats=0.5)],
    )

    with patch("banjo.stream.open_midi_output", return_value=mock_port):
        resolved = stream_progression(req, port_name="MockPort", loop=False)

    assert len(resolved.notes) >= 3
    assert mock_port.send.call_count >= len(resolved.notes) * 2
