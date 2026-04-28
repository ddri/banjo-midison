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

import mido

from banjo.theory import (
    ParsedNumeral,
    ResolvedChord,
    midi_note_name,
    parse_pitch_class,
    parse_roman_numeral,
    pitch_class_name,
    build_chord,
)
from banjo.voice_leading import build_candidates, choose_voicing_position
from banjo.voicings import VoicingName, apply_voicing

TICKS_PER_BEAT = 480  # standard PPQN


@dataclass
class ChordSpec:
    """Per-chord input to the writer."""
    numeral: str
    duration_beats: float
    inversion: int | None = None       # overrides parsed inversion if set
    voicing: VoicingName = "close"


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
    octave: int = 4
    time_signature: str = "4/4"
    humanize: HumanizeSpec = field(default_factory=HumanizeSpec)
    seed: int | None = None
    voice_lead: bool = False
    filename: str | None = None
    prompt_context: str | None = None
    generation_notes: str | None = None


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

        resolved_chords.append((spec, parsed, chord, voiced))
        previous_voiced = voiced

    # Write the MIDI file.
    filename = request.filename or _auto_filename(request)
    if not filename.endswith(".mid"):
        filename += ".mid"
    midi_path = output_dir / filename

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
    current_beat = 0.0
    resolved_metadata: list[dict] = []
    for spec, parsed, chord, voiced in resolved_chords:
        resolved_metadata.append({
            "numeral": spec.numeral,
            "notes": [midi_note_name(n) for n in voiced],
            "midi": list(voiced),
            "start_beat": current_beat,
            "duration_beats": spec.duration_beats,
            "voicing": spec.voicing,
            "inversion": parsed.inversion,
        })
        current_beat += spec.duration_beats

    # Emit MIDI events using absolute ticks, then convert to delta times.
    seconds_per_beat = 60.0 / request.bpm
    ticks_per_ms = TICKS_PER_BEAT / (seconds_per_beat * 1000.0)

    all_events: list[tuple[int, int, str, int, int]] = []
    # (abs_tick, ordering_key, type, note, velocity); ordering_key ensures
    # off-events at the same tick precede on-events.
    current_beat = 0.0
    for spec, parsed, chord, voiced in resolved_chords:
        duration_ticks = int(round(spec.duration_beats * TICKS_PER_BEAT))
        chord_start_tick = int(round(current_beat * TICKS_PER_BEAT))

        for note in voiced:
            velocity = request.humanize.base_velocity
            if request.humanize.velocity_range > 0:
                velocity += rng.randint(-request.humanize.velocity_range, request.humanize.velocity_range)
            velocity = max(1, min(127, velocity))

            timing_offset_ticks = 0
            if request.humanize.timing_ms > 0:
                offset_ms = rng.randint(-request.humanize.timing_ms, request.humanize.timing_ms)
                timing_offset_ticks = int(round(offset_ms * ticks_per_ms))

            on_tick = max(0, chord_start_tick + timing_offset_ticks)
            off_tick = max(on_tick + 1, chord_start_tick + duration_ticks + timing_offset_ticks)
            all_events.append((on_tick, 1, "on", note, velocity))
            all_events.append((off_tick, 0, "off", note, 0))

        current_beat += spec.duration_beats

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
    sidecar_path.write_text(_render_sidecar(request, resolved_metadata, midi_path.name))

    return GenerationResult(
        filepath=midi_path,
        sidecar_path=sidecar_path,
        resolved=resolved_metadata,
        total_beats=current_beat,
    )


def _auto_filename(request: GenerationRequest) -> str:
    """Generate a descriptive filename from the request."""
    key = request.key_center.replace("#", "s").replace("b", "f")
    progression = "-".join(_safe_numeral(c.numeral) for c in request.chords[:6])
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{key}_{request.scale_type}_{progression}_{timestamp}.mid"


def _safe_numeral(n: str) -> str:
    """Strip characters that aren't filesystem-friendly."""
    return n.replace("/", "-of-").replace("°", "o").replace("ø", "h")


def _render_sidecar(
    request: GenerationRequest,
    resolved: list[dict],
    midi_filename: str,
) -> str:
    """Render the human-readable .md sidecar."""
    lines: list[str] = []
    lines.append(f"# {midi_filename}")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
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
    lines.append("| # | Numeral | Beat | Duration | Voicing | Notes |")
    lines.append("|---|---------|------|----------|---------|-------|")
    for i, r in enumerate(resolved, 1):
        notes_str = " ".join(r["notes"])
        lines.append(
            f"| {i} | `{r['numeral']}` | {r['start_beat']} | "
            f"{r['duration_beats']} | {r['voicing']} | {notes_str} |"
        )
    lines.append("")

    return "\n".join(lines)
