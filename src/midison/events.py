"""
Shared note event generator for Banjo.

Translates high-level chord progression requests into deterministic,
timed MIDI note events (pitch, start_beat, duration_beats, velocity).
Shared across MIDI file writer, real-time virtual streaming,
AbletonOSC direct clip injection, and Max for Live MIDI Tools.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from midison.grooves import get_groove, select_voices, tile_groove_pulses
from midison.theory import (
    ParsedNumeral,
    ResolvedChord,
    build_chord,
    midi_note_name,
    parse_pitch_class,
    parse_roman_numeral,
)
from midison.voice_leading import build_candidates, choose_voicing_position
from midison.voicings import apply_voicing

if TYPE_CHECKING:
    from midison.midi_writer import ChordSpec, GenerationRequest, HumanizeSpec


@dataclass(frozen=True)
class TimedNote:
    """A timed MIDI note event in musical beats."""

    pitch: int
    start_beat: float
    duration_beats: float
    velocity: int = 80


@dataclass(frozen=True)
class ResolvedProgression:
    """The complete harmonic and rhythmic resolution of a progression."""

    notes: list[TimedNote]
    resolved_metadata: list[dict]
    total_beats: float


def _clamp_to_max_octave(notes: list[int], max_octave: int) -> list[int]:
    max_midi = (max_octave + 1) * 12 + 11
    clamped: list[int] = []
    for n in notes:
        while n > max_midi:
            n -= 12
        clamped.append(n)
    return clamped


def _calc_velocity(humanize: HumanizeSpec, rng: random.Random, velocity_scale: float = 1.0) -> int:
    base = humanize.base_velocity * velocity_scale
    velocity = int(round(base))
    if humanize.velocity_range > 0:
        velocity += rng.randint(-humanize.velocity_range, humanize.velocity_range)
    return max(1, min(127, velocity))


def resolve_progression_notes(request: GenerationRequest) -> ResolvedProgression:
    """
    Resolves a GenerationRequest into timed MIDI note events and chord metadata.
    Fully accounts for key, mode, inversions, voice leading, voicings, rootless,
    octave limits, and groove pulse patterns.
    """
    rng = random.Random(request.seed) if request.seed is not None else random.Random()
    key_pc = parse_pitch_class(request.key_center)

    resolved_chords: list[tuple[ChordSpec, ParsedNumeral, ResolvedChord, list[int]]] = []
    previous_voiced: list[int] | None = None

    for spec in request.chords:
        parsed = parse_roman_numeral(spec.numeral)
        explicit_inversion = parsed.inversion > 0 or spec.inversion is not None
        if spec.inversion is not None:
            parsed.inversion = spec.inversion
        chord = build_chord(parsed, key_pc, request.scale_type, octave=request.octave)

        if request.voice_lead and previous_voiced is not None:
            candidates = build_candidates(
                parsed,
                key_pc,
                request.scale_type,
                request.octave,
                spec.voicing,
                explicit_inversion,
            )
            chosen_inv, voiced = choose_voicing_position(candidates, previous_voiced)
            parsed.inversion = chosen_inv
        else:
            voiced = apply_voicing(list(chord.midi_notes), spec.voicing)

        if spec.rootless:
            voiced = apply_voicing(voiced, "rootless")

        voiced = _clamp_to_max_octave(voiced, request.max_octave)
        resolved_chords.append((spec, parsed, chord, voiced))
        previous_voiced = voiced

    beat_offsets: list[float] = []
    _beat = 0.0
    for spec, *_ in resolved_chords:
        beat_offsets.append(_beat)
        _beat += spec.duration_beats
    total_beats = _beat

    resolved_metadata: list[dict] = []
    for i, (spec, parsed, chord, voiced) in enumerate(resolved_chords):
        resolved_metadata.append(
            {
                "numeral": spec.numeral,
                "notes": [midi_note_name(n) for n in voiced],
                "midi": list(voiced),
                "start_beat": beat_offsets[i],
                "duration_beats": spec.duration_beats,
                "voicing": spec.voicing,
                "inversion": parsed.inversion,
                "pattern": spec.pattern,
            }
        )

    timed_notes: list[TimedNote] = []
    seconds_per_beat = 60.0 / request.bpm

    for i, (spec, parsed, chord, voiced) in enumerate(resolved_chords):
        chord_start_beat = beat_offsets[i]
        chord_duration = spec.duration_beats
        pattern = spec.pattern

        if pattern == "strum" and len(voiced) > 1:
            # 15ms converted to beats
            strum_step_beats = 0.015 / seconds_per_beat
            sorted_voiced = sorted(voiced)
            for idx, note in enumerate(sorted_voiced):
                note_start = chord_start_beat + idx * strum_step_beats
                note_dur = max(0.1, (chord_start_beat + chord_duration) - note_start)
                velocity = _calc_velocity(request.humanize, rng)
                timed_notes.append(
                    TimedNote(
                        pitch=note,
                        start_beat=round(note_start, 4),
                        duration_beats=round(note_dur, 4),
                        velocity=velocity,
                    )
                )

        elif pattern in ("arpeggio_up", "arpeggio_down") and len(voiced) > 0:
            notes_order = sorted(voiced) if pattern == "arpeggio_up" else sorted(voiced, reverse=True)
            step_beats = chord_duration / len(notes_order)
            for idx, note in enumerate(notes_order):
                note_start = chord_start_beat + idx * step_beats
                note_dur = step_beats
                velocity = _calc_velocity(request.humanize, rng)
                timed_notes.append(
                    TimedNote(
                        pitch=note,
                        start_beat=round(note_start, 4),
                        duration_beats=round(note_dur, 4),
                        velocity=velocity,
                    )
                )

        elif len(voiced) > 0:
            try:
                groove = get_groove(pattern)
            except ValueError:
                groove = get_groove("block")

            pulses = tile_groove_pulses(groove, spec.duration_beats)
            for pulse in pulses:
                pulse_start = chord_start_beat + pulse.beat_offset
                pulse_end = min(chord_start_beat + chord_duration, pulse_start + pulse.duration_beats)
                pulse_dur = max(0.05, pulse_end - pulse_start)
                target_notes = select_voices(voiced, pulse.voice_target)
                for note in target_notes:
                    velocity = _calc_velocity(
                        request.humanize, rng, velocity_scale=pulse.velocity_scale
                    )
                    timed_notes.append(
                        TimedNote(
                            pitch=note,
                            start_beat=round(pulse_start, 4),
                            duration_beats=round(pulse_dur, 4),
                            velocity=velocity,
                        )
                    )

    # Sort notes by start_beat, then pitch
    timed_notes.sort(key=lambda n: (n.start_beat, n.pitch))

    return ResolvedProgression(
        notes=timed_notes,
        resolved_metadata=resolved_metadata,
        total_beats=total_beats,
    )
