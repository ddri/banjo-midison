"""
MIDI file output + sidecar markdown.

The writer is deterministic given a seed; humanization is the only source
of randomness and is reproducible when seed is provided.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from typing import Literal

import mido

from midison.theory import (
    ParsedNumeral,
    ResolvedChord,
    midi_note_name,
    parse_pitch_class,
    parse_roman_numeral,
    pitch_class_name,
    build_chord,
)
from midison.grooves import get_groove, select_voices, tile_groove_pulses
from midison.voice_leading import build_candidates, choose_voicing_position
from midison.voicings import VoicingName, apply_voicing

TICKS_PER_BEAT = 480  # standard PPQN

PatternName = str  # 'block', 'strum', 'arpeggio_up', 'charleston', 'bossa', etc.


@dataclass
class ChordSpec:
    """Per-chord input to the writer."""
    numeral: str
    duration_beats: float
    inversion: int | None = None       # overrides parsed inversion if set
    voicing: VoicingName = "close"
    rootless: bool = False
    pattern: PatternName = "block"


@dataclass
class HumanizeSpec:
    velocity_range: int = 0    # max +/- deviation from base_velocity
    timing_ms: int = 0         # max +/- deviation in milliseconds
    base_velocity: int = 80


@dataclass
class GenerationRequest:
    key_center: str
    scale_type: str
    bpm: int
    chords: list[ChordSpec]
    octave: int = 3
    time_signature: str = "4/4"
    humanize: HumanizeSpec = field(default_factory=HumanizeSpec)
    seed: int | None = None
    voice_lead: bool = False
    filename: str | None = None
    prompt_context: str | None = None
    generation_notes: str | None = None
    max_octave: int = 5


@dataclass
class GenerationResult:
    filepath: Path
    sidecar_path: Path
    resolved: list[dict]
    total_beats: float


def generate(request: GenerationRequest, output_dir: Path) -> GenerationResult:
    """
    Generate a .mid file and its .md sidecar in output_dir.
    Returns paths and resolved chord metadata.
    """
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc)

    rng = random.Random(request.seed) if request.seed is not None else random.Random()

    key_pc = parse_pitch_class(request.key_center)

    # Resolve every chord into MIDI notes.
    resolved_chords: list[tuple[ChordSpec, ParsedNumeral, ResolvedChord, list[int]]] = []
    previous_voiced: list[int] | None = None
    for spec in request.chords:
        parsed = parse_roman_numeral(spec.numeral)
        # Track explicitness BEFORE overriding so voice leading respects user intent.
        # spec.inversion=0 counts as explicit (user named root deliberately, per MCP
        # schema "omit this" guidance); only None means "implicit, optimizer free to pick".
        explicit_inversion = parsed.inversion > 0 or spec.inversion is not None
        if spec.inversion is not None:
            parsed.inversion = spec.inversion
        chord = build_chord(parsed, key_pc, request.scale_type, octave=request.octave)

        # Step 1-2: apply voicing (voice-led or direct)
        if request.voice_lead and previous_voiced is not None:
            candidates = build_candidates(
                parsed, key_pc, request.scale_type, request.octave,
                spec.voicing, explicit_inversion,
            )
            chosen_inv, voiced = choose_voicing_position(candidates, previous_voiced)
            # Update parsed.inversion so the resolved metadata reports the
            # actually-chosen inversion (not the original parse value, which
            # build_candidates did not mutate).
            parsed.inversion = chosen_inv
        else:
            voiced = apply_voicing(list(chord.midi_notes), spec.voicing)

        # Step 3: rootless — strip root after voice leading so VL sees the full chord
        if spec.rootless:
            voiced = apply_voicing(voiced, "rootless")

        # Step 4: max_octave clamp — hard ceiling applied last
        voiced = _clamp_to_max_octave(voiced, request.max_octave)

        resolved_chords.append((spec, parsed, chord, voiced))
        previous_voiced = voiced

    # Pre-compute beat offsets once; both the metadata loop and MIDI event loop use them.
    beat_offsets: list[float] = []
    _beat = 0.0
    for spec, *_ in resolved_chords:
        beat_offsets.append(_beat)
        _beat += spec.duration_beats
    total_beats = _beat

    # Write the MIDI file.
    filename = request.filename or _auto_filename(request, generated_at)
    if not filename.endswith(".mid"):
        filename += ".mid"
    midi_path = output_dir / Path(filename).name

    mid = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    # Tempo + time signature meta-events.
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(request.bpm), time=0))
    num, den = (int(x) for x in request.time_signature.split("/"))
    track.append(mido.MetaMessage(
        "time_signature",
        numerator=num,
        denominator=den,
        clocks_per_click=24,
        notated_32nd_notes_per_beat=8,
        time=0,
    ))

    # Build resolved metadata for each chord.
    resolved_metadata: list[dict] = []
    for i, (spec, parsed, chord, voiced) in enumerate(resolved_chords):
        resolved_metadata.append({
            "numeral": spec.numeral,
            "notes": [midi_note_name(n) for n in voiced],
            "midi": list(voiced),
            "start_beat": beat_offsets[i],
            "duration_beats": spec.duration_beats,
            "voicing": spec.voicing,
            "inversion": parsed.inversion,
            "pattern": spec.pattern,
        })

    # Emit MIDI events using absolute ticks, then convert to delta times.
    seconds_per_beat = 60.0 / request.bpm
    ticks_per_ms = TICKS_PER_BEAT / (seconds_per_beat * 1000.0)

    all_events: list[tuple[int, int, str, int, int]] = []
    # (abs_tick, ordering_key, type, note, velocity); ordering_key ensures
    # off-events at the same tick precede on-events.
    for i, (spec, parsed, chord, voiced) in enumerate(resolved_chords):
        duration_ticks = int(round(spec.duration_beats * TICKS_PER_BEAT))
        chord_start_tick = int(round(beat_offsets[i] * TICKS_PER_BEAT))

        pattern = spec.pattern
        if pattern == "strum" and len(voiced) > 1:
            strum_step_ticks = int(round(15.0 * ticks_per_ms))
            sorted_voiced = sorted(voiced)
            for idx, note in enumerate(sorted_voiced):
                note_start = chord_start_tick + idx * strum_step_ticks
                note_end = chord_start_tick + duration_ticks
                velocity = _calc_velocity(request.humanize, rng)
                timing_ticks = _calc_timing_offset(request.humanize, rng, ticks_per_ms)
                on_tick = max(0, note_start + timing_ticks)
                off_tick = max(on_tick + 1, note_end + timing_ticks)
                all_events.append((on_tick, 1, "on", note, velocity))
                all_events.append((off_tick, 0, "off", note, 0))

        elif pattern in ("arpeggio_up", "arpeggio_down") and len(voiced) > 0:
            notes_order = sorted(voiced) if pattern == "arpeggio_up" else sorted(voiced, reverse=True)
            step_ticks = duration_ticks / len(notes_order)
            for idx, note in enumerate(notes_order):
                note_start = chord_start_tick + int(round(idx * step_ticks))
                note_end = chord_start_tick + int(round((idx + 1) * step_ticks))
                velocity = _calc_velocity(request.humanize, rng)
                timing_ticks = _calc_timing_offset(request.humanize, rng, ticks_per_ms)
                on_tick = max(0, note_start + timing_ticks)
                off_tick = max(on_tick + 1, note_end + timing_ticks)
                all_events.append((on_tick, 1, "on", note, velocity))
                all_events.append((off_tick, 0, "off", note, 0))

        elif len(voiced) > 0:
            # Look up groove template and tile pulses across chord duration
            try:
                groove = get_groove(pattern)
            except ValueError:
                groove = get_groove("block")

            pulses = tile_groove_pulses(groove, spec.duration_beats)
            for pulse in pulses:
                p_start_tick = chord_start_tick + int(round(pulse.beat_offset * TICKS_PER_BEAT))
                p_dur_ticks = int(round(pulse.duration_beats * TICKS_PER_BEAT))
                p_end_tick = min(chord_start_tick + duration_ticks, p_start_tick + p_dur_ticks)
                target_notes = select_voices(voiced, pulse.voice_target)
                for note in target_notes:
                    velocity = _calc_velocity(request.humanize, rng, velocity_scale=pulse.velocity_scale)
                    timing_ticks = _calc_timing_offset(request.humanize, rng, ticks_per_ms)
                    on_tick = max(0, p_start_tick + timing_ticks)
                    off_tick = max(on_tick + 1, p_end_tick + timing_ticks)
                    all_events.append((on_tick, 1, "on", note, velocity))
                    all_events.append((off_tick, 0, "off", note, 0))

    all_events.sort(key=lambda e: (e[0], e[1]))

    prev_tick = 0
    for abs_tick, _ord, etype, note, vel in all_events:
        delta = abs_tick - prev_tick
        if etype == "on":
            track.append(mido.Message("note_on", note=note, velocity=vel, time=delta))
        else:
            track.append(mido.Message("note_off", note=note, velocity=0, time=delta))
        prev_tick = abs_tick

    mid.save(midi_path)

    # Sidecar.
    sidecar_path = midi_path.with_suffix(".md")
    sidecar_path.write_text(_render_sidecar(request, resolved_metadata, midi_path.name, generated_at))

    return GenerationResult(
        filepath=midi_path,
        sidecar_path=sidecar_path,
        resolved=resolved_metadata,
        total_beats=total_beats,
    )


def _calc_velocity(humanize: HumanizeSpec, rng: random.Random, velocity_scale: float = 1.0) -> int:
    base = humanize.base_velocity * velocity_scale
    velocity = int(round(base))
    if humanize.velocity_range > 0:
        velocity += rng.randint(-humanize.velocity_range, humanize.velocity_range)
    return max(1, min(127, velocity))


def _calc_timing_offset(humanize: HumanizeSpec, rng: random.Random, ticks_per_ms: float) -> int:
    if humanize.timing_ms > 0:
        offset_ms = rng.randint(-humanize.timing_ms, humanize.timing_ms)
        return int(round(offset_ms * ticks_per_ms))
    return 0


def _clamp_to_max_octave(notes: list[int], max_octave: int) -> list[int]:
    """Shift notes down by whole octaves until the lowest note is within max_octave.

    Uses Ableton convention: C3 = MIDI 60, so octave N lowest note = 12*(N+2).
    """
    if not notes:
        return notes
    lowest_octave = (min(notes) // 12) - 2  # Ableton: C3=60 → (60//12)-2 = 3
    if lowest_octave > max_octave:
        shift = (lowest_octave - max_octave) * 12
        return [n - shift for n in notes]
    return notes


def _auto_filename(request: GenerationRequest, generated_at: datetime) -> str:
    """Generate a descriptive filename from the request."""
    key = request.key_center.replace("#", "s").replace("b", "f")
    progression = "-".join(_safe_numeral(c.numeral) for c in request.chords[:6])
    timestamp = generated_at.strftime("%Y%m%d-%H%M%S")
    return f"{key}_{request.scale_type}_{progression}_{timestamp}.mid"


def _safe_numeral(n: str) -> str:
    """Strip characters that aren't filesystem-friendly."""
    return (
        n.replace("/", "-of-")
        .replace("°", "o")
        .replace("ø", "h")
        .replace("#", "s")
        .replace("+", "aug")
    )


def _render_sidecar(
    request: GenerationRequest,
    resolved: list[dict],
    midi_filename: str,
    generated_at: datetime,
) -> str:
    """Render the human-readable .md sidecar."""
    lines: list[str] = []
    lines.append(f"# {midi_filename}")
    lines.append("")
    lines.append(f"Generated: {generated_at.isoformat()}")
    lines.append("")

    if request.prompt_context:
        lines.append("## Prompt context")
        lines.append("")
        lines.append(request.prompt_context.strip())
        lines.append("")

    if request.generation_notes:
        lines.append("## Generation notes")
        lines.append("")
        lines.append(request.generation_notes.strip())
        lines.append("")

    lines.append("## Parameters")
    lines.append("")
    lines.append(f"- Key: {request.key_center} {request.scale_type}")
    lines.append(f"- Tempo: {request.bpm} BPM")
    lines.append(f"- Time signature: {request.time_signature}")
    lines.append(f"- Octave: {request.octave}")
    if request.seed is not None:
        lines.append(f"- Seed: {request.seed}")
    if request.humanize.velocity_range or request.humanize.timing_ms:
        lines.append(
            f"- Humanize: velocity ±{request.humanize.velocity_range}, "
            f"timing ±{request.humanize.timing_ms}ms, "
            f"base velocity {request.humanize.base_velocity}"
        )
    lines.append("")

    lines.append("## Resolved progression")
    lines.append("")
    lines.append("| # | Numeral | Beat | Duration | Voicing | Pattern | Notes |")
    lines.append("|---|---------|------|----------|---------|---------|-------|")
    for i, r in enumerate(resolved, 1):
        notes_str = " ".join(r["notes"])
        lines.append(
            f"| {i} | `{r['numeral']}` | {r['start_beat']} | "
            f"{r['duration_beats']} | {r['voicing']} | {r.get('pattern', 'block')} | {notes_str} |"
        )
    lines.append("")

    return "\n".join(lines)
