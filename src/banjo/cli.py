"""
Command-line interface for banjo: generate MIDI chord progressions directly.

Usage:
    banjo "ii7 - V7 - Imaj7"
    banjo "ii7:2 - V7:2 - Imaj7:4" -k G --bpm 100 --pattern arpeggio_up --voice-lead
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from banjo import config
from banjo.grooves import list_grooves
from banjo.midi_writer import (
    ChordSpec,
    GenerationRequest,
    HumanizeSpec,
    PatternName,
    generate,
)
from banjo.theory import MODE_INTERVALS, parse_pitch_class, parse_roman_numeral
from banjo.voicings import VoicingName

VALID_VOICINGS: tuple[VoicingName, ...] = (
    "close",
    "drop2",
    "drop3",
    "drop2and4",
    "spread",
)
VALID_PATTERNS: tuple[PatternName, ...] = tuple(list_grooves())


def parse_progression_string(
    prog_str: str,
    default_beats: float = 4.0,
    default_voicing: VoicingName = "close",
    default_pattern: PatternName = "block",
    default_rootless: bool = False,
) -> list[ChordSpec]:
    """
    Parse a progression string into a list of ChordSpecs.

    Tokens can be separated by whitespace, dashes ('-'), or commas (',').
    Each token may specify duration in beats using a colon suffix (e.g. 'ii7:2' or 'V7:2.5').
    """
    s = prog_str.strip()
    if not s:
        raise ValueError("Progression string cannot be empty")

    # Split on commas, dashes (outside of secondary chords like V/vi or accidentals like bVII), or whitespace
    # Replace comma or dash with space when used as a delimiter
    cleaned = re.sub(r"\s*,\s*|\s+-\s+|\s+", " ", s).strip()
    tokens = [t.strip() for t in cleaned.split(" ") if t.strip()]

    if not tokens:
        raise ValueError("No chord tokens found in progression")

    chords: list[ChordSpec] = []
    for i, tok in enumerate(tokens):
        if ":" in tok:
            numeral, dur_str = tok.rsplit(":", 1)
            try:
                duration = float(dur_str)
                if duration <= 0:
                    raise ValueError
            except ValueError:
                raise ValueError(f"Invalid duration '{dur_str}' in token '{tok}'")
        else:
            numeral = tok
            duration = default_beats

        # Validate Roman numeral syntax early
        try:
            parse_roman_numeral(numeral)
        except Exception as e:
            raise ValueError(f"Invalid Roman numeral '{numeral}' at chord {i + 1}: {e}")

        chords.append(
            ChordSpec(
                numeral=numeral,
                duration_beats=duration,
                voicing=default_voicing,
                rootless=default_rootless,
                pattern=default_pattern,
            )
        )

    return chords


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="banjo",
        description="Generate MIDI chord progressions from Roman numeral analysis.",
    )
    parser.add_argument(
        "progression",
        help="Roman numeral progression string, e.g. 'ii7 - V7 - Imaj7' or 'ii7:2 - V7:2 - Imaj7:4'",
    )
    parser.add_argument(
        "-k",
        "--key",
        default="C",
        help="Tonic note name, e.g. C, F#, Bb, Eb (default: C)",
    )
    parser.add_argument(
        "-m",
        "--mode",
        dest="scale_type",
        default="major",
        choices=sorted(MODE_INTERVALS.keys()),
        help="Mode/scale of the key (default: major)",
    )
    parser.add_argument(
        "-b",
        "--bpm",
        type=int,
        default=120,
        help="Tempo in beats per minute (default: 120)",
    )
    parser.add_argument(
        "-d",
        "--beats",
        type=float,
        default=4.0,
        help="Default duration in beats per chord when not specified via :beats (default: 4.0)",
    )
    parser.add_argument(
        "-v",
        "--voicing",
        default="close",
        choices=VALID_VOICINGS,
        help="Voicing transformation applied to chords (default: close)",
    )
    parser.add_argument(
        "-p",
        "--pattern",
        default="block",
        choices=VALID_PATTERNS,
        help="Playback rhythm pattern (default: block)",
    )
    parser.add_argument(
        "-r",
        "--rootless",
        action="store_true",
        help="Omit the root note from generated chords",
    )
    parser.add_argument(
        "-vl",
        "--voice-lead",
        action="store_true",
        help="Jointly optimize inversion and octave to minimize voice movement",
    )
    parser.add_argument(
        "-o",
        "--octave",
        type=int,
        default=3,
        help="Root octave register (default: 3)",
    )
    parser.add_argument(
        "--max-octave",
        type=int,
        default=5,
        help="Hard ceiling on chord register (default: 5)",
    )
    parser.add_argument(
        "--humanize",
        action="store_true",
        help="Apply default velocity and timing humanization",
    )
    parser.add_argument(
        "--velocity-range",
        type=int,
        default=0,
        help="Velocity deviation +/- range (default: 0)",
    )
    parser.add_argument(
        "--timing-ms",
        type=int,
        default=0,
        help="Timing deviation +/- in milliseconds (default: 0)",
    )
    parser.add_argument(
        "--base-velocity",
        type=int,
        default=80,
        help="Center velocity (default: 80)",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="Random seed for reproducible humanization",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (defaults to ~/.banjo/config.json or ~/Music/banjo/)",
    )
    parser.add_argument(
        "-f",
        "--filename",
        help="Output filename without .mid extension",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        parse_pitch_class(args.key)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.voicing == "spread" and args.rootless:
        print(
            "Error: rootless cannot be combined with voicing: spread (spread requires a bass root).",
            file=sys.stderr,
        )
        return 1

    try:
        chords = parse_progression_string(
            args.progression,
            default_beats=args.beats,
            default_voicing=args.voicing,
            default_pattern=args.pattern,
            default_rootless=args.rootless,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    velocity_range = args.velocity_range
    timing_ms = args.timing_ms
    if args.humanize:
        if velocity_range == 0:
            velocity_range = 10
        if timing_ms == 0:
            timing_ms = 6

    humanize = HumanizeSpec(
        velocity_range=velocity_range,
        timing_ms=timing_ms,
        base_velocity=args.base_velocity,
    )

    request = GenerationRequest(
        key_center=args.key,
        scale_type=args.scale_type,
        bpm=args.bpm,
        chords=chords,
        octave=args.octave,
        max_octave=args.max_octave,
        humanize=humanize,
        seed=args.seed,
        voice_lead=args.voice_lead,
        filename=args.filename,
    )

    output_dir = args.output_dir or config.get_output_directory()

    try:
        result = generate(request, output_dir)
    except Exception as e:
        print(f"Error generating MIDI: {e}", file=sys.stderr)
        return 1

    print("\n✓ Generated MIDI progression:")
    print(f"  File:     {result.filepath}")
    print(f"  Sidecar:  {result.sidecar_path}")
    print(
        f"  Details:  {args.key} {args.scale_type} | {args.bpm} BPM | {result.total_beats:.1f} beats total\n"
    )

    header = f"  {'#':<3} {'Numeral':<10} {'Start':<7} {'Dur':<6} {'Voicing':<10} {'Pattern':<12} {'Notes'}"
    print(header)
    print("  " + "-" * (len(header) + 10))
    for i, r in enumerate(result.resolved, 1):
        notes_str = " ".join(r["notes"])
        print(
            f"  {i:<3} {r['numeral']:<10} {r['start_beat']:<7.1f} {r['duration_beats']:<6.1f} "
            f"{r['voicing']:<10} {r.get('pattern', 'block'):<12} {notes_str}"
        )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
