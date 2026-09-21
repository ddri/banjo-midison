"""
Real-time Virtual MIDI streaming for Banjo.

Streams voice-led chord progressions and groove pulses directly into
a macOS CoreMIDI virtual port or existing MIDI port (e.g., IAC Driver).
Armed tracks in Ableton Live receive and play notes through VSTs with zero latency.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import mido

from banjo.events import ResolvedProgression, TimedNote, resolve_progression_notes
from banjo.midi_writer import GenerationRequest

logger = logging.getLogger("banjo.stream")


def get_available_output_ports() -> list[str]:
    """Return a list of available hardware/virtual MIDI output ports."""
    try:
        return mido.get_output_names()
    except Exception as exc:
        logger.warning(f"Error querying MIDI output ports: {exc}")
        return []


def open_midi_output(port_name: str = "Banjo") -> mido.ports.BaseOutput:
    """
    Open a MIDI output port. Attempts to create a virtual port first.
    If virtual ports are not supported by the backend, falls back to an existing port.
    """
    try:
        return mido.open_output(port_name, virtual=True)
    except (NotImplementedError, ValueError):
        # Fallback to existing port if virtual port creation fails
        available = get_available_output_ports()
        for p in available:
            if port_name.lower() in p.lower():
                return mido.open_output(p)
        if available:
            return mido.open_output(available[0])
        return mido.open_output(port_name)


def stop_all_notes(port: mido.ports.BaseOutput, channel: int = 0) -> None:
    """Send All Notes Off and All Sound Off to prevent hanging notes."""
    try:
        # All Notes Off (CC 123)
        port.send(mido.Message("control_change", channel=channel, control=123, value=0))
        # All Sound Off (CC 120)
        port.send(mido.Message("control_change", channel=channel, control=120, value=0))
        # Also send explicit note_off for all pitches as failsafe
        for note in range(128):
            port.send(mido.Message("note_off", channel=channel, note=note, velocity=0))
    except Exception as exc:
        logger.debug(f"Failed to send all notes off: {exc}")


def stream_notes(
    notes: list[TimedNote],
    bpm: int = 120,
    total_beats: float | None = None,
    port: mido.ports.BaseOutput | None = None,
    port_name: str = "Banjo",
    loop: bool = False,
    stop_event: threading.Event | None = None,
    on_event: Callable[[str, int, float], None] | None = None,
) -> int:
    """
    Stream timed MIDI notes in real-time to a MIDI port.

    Args:
        notes: List of TimedNotes to stream.
        bpm: Beats per minute for tempo timing.
        total_beats: Total cycle length in beats. If None, derived from max note end.
        port: Pre-opened mido output port, or None to create/open port_name.
        port_name: Name of the port to open if port is None.
        loop: If True, loop playback until stop_event is set or KeyboardInterrupt.
        stop_event: Optional threading.Event to signal stopping playback.
        on_event: Optional callback(event_type, pitch, timestamp_sec).

    Returns:
        The total count of MIDI messages sent.
    """
    if not notes:
        return 0

    close_port_on_exit = False
    if port is None:
        port = open_midi_output(port_name)
        close_port_on_exit = True

    seconds_per_beat = 60.0 / bpm

    if total_beats is None:
        total_beats = max(n.start_beat + n.duration_beats for n in notes)
    total_duration_sec = total_beats * seconds_per_beat

    # Build sorted list of (time_sec, event_type, pitch, velocity)
    # Event types: "off" comes before "on" at the exact same timestamp
    events: list[tuple[float, int, str, int, int]] = []
    for n in notes:
        on_sec = n.start_beat * seconds_per_beat
        off_sec = (n.start_beat + n.duration_beats) * seconds_per_beat
        events.append((on_sec, 1, "on", n.pitch, n.velocity))
        events.append((off_sec, 0, "off", n.pitch, 0))

    events.sort(key=lambda e: (e[0], e[1]))

    messages_sent = 0

    try:
        while True:
            cycle_start = time.perf_counter()

            for event_sec, _ord, etype, pitch, velocity in events:
                if stop_event is not None and stop_event.is_set():
                    return messages_sent

                target_time = cycle_start + event_sec
                now = time.perf_counter()
                sleep_sec = target_time - now

                # Sleep if we have more than 2ms remaining
                if sleep_sec > 0.002:
                    time.sleep(sleep_sec - 0.001)

                # Busy wait the remaining sub-millisecond for microsecond precision
                while time.perf_counter() < target_time:
                    pass

                # Dispatch message
                if etype == "on":
                    msg = mido.Message("note_on", note=pitch, velocity=velocity)
                else:
                    msg = mido.Message("note_off", note=pitch, velocity=0)

                port.send(msg)
                messages_sent += 1

                if on_event:
                    on_event(etype, pitch, time.perf_counter() - cycle_start)

            # Wait out the rest of the total cycle before looping
            cycle_end = cycle_start + total_duration_sec
            while time.perf_counter() < cycle_end:
                if stop_event is not None and stop_event.is_set():
                    return messages_sent
                time.sleep(0.005)

            if not loop:
                break

    except KeyboardInterrupt:
        pass
    finally:
        stop_all_notes(port)
        if close_port_on_exit:
            try:
                port.close()
            except Exception:
                pass

    return messages_sent


def stream_progression(
    request: GenerationRequest,
    port_name: str = "Banjo",
    loop: bool = False,
    stop_event: threading.Event | None = None,
) -> ResolvedProgression:
    """
    Convenience function: resolves a GenerationRequest and streams it in real-time.
    """
    resolved = resolve_progression_notes(request)
    stream_notes(
        notes=resolved.notes,
        bpm=request.bpm,
        total_beats=resolved.total_beats,
        port_name=port_name,
        loop=loop,
        stop_event=stop_event,
    )
    return resolved
