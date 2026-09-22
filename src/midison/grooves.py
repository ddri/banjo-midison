"""
Groove and performance pattern templates for midison.

Decouples harmonic chord voicings from rhythmic performance expressions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VoiceTarget = Literal["all", "bass", "upper"]


@dataclass(frozen=True)
class Pulse:
    """A single rhythmic note onset within a groove pattern."""

    beat_offset: float
    duration_beats: float
    velocity_scale: float = 1.0
    voice_target: VoiceTarget = "all"


@dataclass(frozen=True)
class Groove:
    """A collection of pulses that define a rhythmic comping groove."""

    name: str
    description: str
    meter_beats: float
    pulses: tuple[Pulse, ...]


# Built-in groove definitions
_GROOVES_LIST: list[Groove] = [
    Groove(
        name="block",
        description="Simultaneous sustained chord tones for the full duration.",
        meter_beats=4.0,
        pulses=(Pulse(beat_offset=0.0, duration_beats=4.0, velocity_scale=1.0, voice_target="all"),),
    ),
    Groove(
        name="charleston",
        description="Classic dotted-quarter (beat 1) and eighth-note stab (and-of-2) (Jazz, Neo-soul, House).",
        meter_beats=4.0,
        pulses=(
            Pulse(beat_offset=0.0, duration_beats=1.0, velocity_scale=1.10, voice_target="all"),
            Pulse(beat_offset=1.5, duration_beats=0.5, velocity_scale=0.95, voice_target="all"),
        ),
    ),
    Groove(
        name="four_on_floor",
        description="Driving quarter-note pulses with alternating velocity accents (Indie rock, House piano).",
        meter_beats=4.0,
        pulses=(
            Pulse(beat_offset=0.0, duration_beats=0.5, velocity_scale=1.10, voice_target="all"),
            Pulse(beat_offset=1.0, duration_beats=0.5, velocity_scale=0.90, voice_target="all"),
            Pulse(beat_offset=2.0, duration_beats=0.5, velocity_scale=1.00, voice_target="all"),
            Pulse(beat_offset=3.0, duration_beats=0.5, velocity_scale=0.92, voice_target="all"),
        ),
    ),
    Groove(
        name="bossa",
        description="Brazilian Bossa Nova syncopation with half-note bass and offbeat upper chord stabs.",
        meter_beats=4.0,
        pulses=(
            Pulse(beat_offset=0.0, duration_beats=1.5, velocity_scale=1.05, voice_target="bass"),
            Pulse(beat_offset=2.0, duration_beats=1.5, velocity_scale=1.00, voice_target="bass"),
            Pulse(beat_offset=0.0, duration_beats=0.5, velocity_scale=1.00, voice_target="upper"),
            Pulse(beat_offset=1.5, duration_beats=0.5, velocity_scale=0.95, voice_target="upper"),
            Pulse(beat_offset=2.5, duration_beats=0.5, velocity_scale=0.95, voice_target="upper"),
            Pulse(beat_offset=3.5, duration_beats=0.5, velocity_scale=0.90, voice_target="upper"),
        ),
    ),
    Groove(
        name="tresillo",
        description="3+3+2 syncopation (beats 0.0, 1.5, 3.0), foundational to Latin, Afrobeats, and modern pop.",
        meter_beats=4.0,
        pulses=(
            Pulse(beat_offset=0.0, duration_beats=0.8, velocity_scale=1.15, voice_target="all"),
            Pulse(beat_offset=1.5, duration_beats=0.8, velocity_scale=1.05, voice_target="all"),
            Pulse(beat_offset=3.0, duration_beats=0.8, velocity_scale=0.95, voice_target="all"),
        ),
    ),
    Groove(
        name="reggae_skank",
        description="Upbeat offbeat chops on the 'and' of each beat (Reggae, Dub, Ska).",
        meter_beats=4.0,
        pulses=(
            Pulse(beat_offset=0.5, duration_beats=0.35, velocity_scale=1.05, voice_target="upper"),
            Pulse(beat_offset=1.5, duration_beats=0.35, velocity_scale=0.95, voice_target="upper"),
            Pulse(beat_offset=2.5, duration_beats=0.35, velocity_scale=1.00, voice_target="upper"),
            Pulse(beat_offset=3.5, duration_beats=0.35, velocity_scale=0.90, voice_target="upper"),
        ),
    ),
    Groove(
        name="waltz",
        description="3/4 meter comping: bass anchor on beat 1, upper chord chops on beats 2 and 3.",
        meter_beats=3.0,
        pulses=(
            Pulse(beat_offset=0.0, duration_beats=0.85, velocity_scale=1.10, voice_target="bass"),
            Pulse(beat_offset=1.0, duration_beats=0.65, velocity_scale=0.95, voice_target="upper"),
            Pulse(beat_offset=2.0, duration_beats=0.65, velocity_scale=0.90, voice_target="upper"),
        ),
    ),
    Groove(
        name="comp_syncopated",
        description="Eighth-note syncopated pulse pattern on beats 0.0, 1.5, and 3.0.",
        meter_beats=4.0,
        pulses=(
            Pulse(beat_offset=0.0, duration_beats=0.75, velocity_scale=1.05, voice_target="all"),
            Pulse(beat_offset=1.5, duration_beats=0.75, velocity_scale=0.95, voice_target="all"),
            Pulse(beat_offset=3.0, duration_beats=0.75, velocity_scale=1.00, voice_target="all"),
        ),
    ),
]

GROOVES: dict[str, Groove] = {g.name: g for g in _GROOVES_LIST}

SPECIAL_PATTERNS = {"strum", "arpeggio_up", "arpeggio_down"}


def get_groove(name: str) -> Groove:
    """Retrieve a groove by name, raising ValueError if not found."""
    if name not in GROOVES:
        valid = sorted(set(GROOVES.keys()) | SPECIAL_PATTERNS)
        raise ValueError(f"Unknown pattern/groove: {name!r}. Valid options: {valid}")
    return GROOVES[name]


def list_grooves() -> list[str]:
    """Return all valid pattern and groove names."""
    return sorted(set(GROOVES.keys()) | SPECIAL_PATTERNS)


def tile_groove_pulses(groove: Groove, total_duration_beats: float) -> list[Pulse]:
    """
    Tile a groove's pulse sequence across total_duration_beats.

    If groove is 'block', returns a single pulse spanning the full duration.
    Otherwise repeats the pulses every meter_beats until total_duration_beats is reached.
    """
    if groove.name == "block":
        return [Pulse(beat_offset=0.0, duration_beats=total_duration_beats, velocity_scale=1.0, voice_target="all")]

    pulses: list[Pulse] = []
    cycle = 0
    while True:
        cycle_base = cycle * groove.meter_beats
        if cycle_base >= total_duration_beats:
            break
        for p in groove.pulses:
            p_offset = cycle_base + p.beat_offset
            if p_offset >= total_duration_beats:
                continue
            # Clamp duration if pulse exceeds remaining total duration
            p_dur = min(p.duration_beats, total_duration_beats - p_offset)
            pulses.append(
                Pulse(
                    beat_offset=p_offset,
                    duration_beats=p_dur,
                    velocity_scale=p.velocity_scale,
                    voice_target=p.voice_target,
                )
            )
        cycle += 1

    return pulses


def select_voices(voiced_notes: list[int], target: VoiceTarget) -> list[int]:
    """
    Filter voiced notes according to VoiceTarget ('all', 'bass', 'upper').
    """
    if not voiced_notes:
        return []
    if target == "all" or len(voiced_notes) <= 1:
        return list(voiced_notes)

    sorted_notes = sorted(voiced_notes)
    if target == "bass":
        return [sorted_notes[0]]
    if target == "upper":
        return sorted_notes[1:]

    return list(voiced_notes)
