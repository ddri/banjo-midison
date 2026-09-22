"""
Command-line interface for midison: generate MIDI chord progressions directly.

Usage:
    midison "ii7 - V7 - Imaj7"
    midison "ii7:2 - V7:2 - Imaj7:4" -k G --bpm 100 --pattern arpeggio_up --voice-lead
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from midison import config
from midison.grooves import list_grooves
from midison.midi_writer import (
    ChordSpec,
    GenerationRequest,
    HumanizeSpec,
    PatternName,
    generate,
)
from midison.theory import MODE_INTERVALS, parse_pitch_class, parse_roman_numeral
from midison.voicings import VoicingName
from midison.stream import stream_progression
from midison.ableton import AbletonClient, install_ableton_osc
from midison.miditool import to_miditool_dict, install_m4l_device

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
        prog="midison",
        description="Generate MIDI chord progressions from Roman numeral analysis.",
    )
    parser.add_argument(
        "progression",
        nargs="?",
        default=None,
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
        default=None,
        help="Tempo in beats per minute (default: 120, or auto-synced from Ableton Live session)",
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
        help="Output directory (defaults to ~/.midison/config.json or ~/Music/midison/)",
    )
    parser.add_argument(
        "--play",
        "--stream",
        dest="stream",
        action="store_true",
        help="Stream notes in real-time to macOS virtual MIDI port ('Midison') or specified --port",
    )
    parser.add_argument(
        "--port",
        default="Midison",
        help="Target MIDI port for --play/--stream (default: 'Midison')",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop real-time playback continuously until Ctrl+C",
    )
    parser.add_argument(
        "--to-ableton",
        action="store_true",
        help="Inject clip directly into Ableton Live via AbletonOSC (zero drag-and-drop)",
    )
    parser.add_argument(
        "--track",
        type=int,
        default=None,
        help="Ableton Live track index for --to-ableton (default: active track in Live, or 0)",
    )
    parser.add_argument(
        "--clip",
        type=int,
        default=None,
        help="Ableton Live clip slot index for --to-ableton (default: active clip slot in Live, or 0)",
    )
    parser.add_argument(
        "--no-fire",
        dest="fire",
        action="store_false",
        default=True,
        help="Do not auto-play/fire the clip in Ableton after injection",
    )
    parser.add_argument(
        "--miditool-dict",
        action="store_true",
        help="Print Ableton Live 12 native live.miditool.out JSON note dictionary to stdout",
    )
    parser.add_argument(
        "--install-ableton-osc",
        action="store_true",
        help="Install AbletonOSC into Ableton's User Remote Scripts directory",
    )
    parser.add_argument(
        "--install-m4l",
        action="store_true",
        help="Install Midison Generator.amxd into Ableton Live 12 MIDI Tools",
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

    if args.install_ableton_osc:
        try:
            installed_path = install_ableton_osc()
            print(f"\n✓ Installed AbletonOSC successfully to:")
            print(f"  {installed_path}")
            print("\nNext step in Ableton Live:")
            print("  1. Open Preferences / Settings (Cmd + ,)")
            print("  2. Go to 'Link, Tempo & MIDI'")
            print("  3. Under 'Control Surface', select 'AbletonOSC' from the dropdown.")
            return 0
        except Exception as e:
            print(f"Error installing AbletonOSC: {e}", file=sys.stderr)
            return 1

    if args.install_m4l:
        try:
            installed_path = install_m4l_device()
            print(f"\n✓ Installed Midison Generator.amxd successfully to:")
            print(f"  {installed_path}")
            print("\nNext step in Ableton Live 12:")
            print("  1. Open the Piano Roll / Clip View on any MIDI clip.")
            print("  2. Click the 'Generators' tab.")
            print("  3. Select 'Midison Generator' to compose chords and grooves directly inside Live!")
            return 0
        except Exception as e:
            print(f"Error installing Max for Live MIDI tool: {e}", file=sys.stderr)
            return 1

    if not args.progression:
        parser.print_help()
        return 1

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

    bpm = args.bpm
    target_track = args.track
    target_clip = args.clip

    if args.to_ableton:
        client = AbletonClient()
        session_state = client.query_session_state()
        if getattr(session_state, "connected", False) is True:
            if target_track is None:
                target_track = session_state.selected_track
            if target_clip is None:
                target_clip = session_state.selected_scene
            if bpm is None:
                bpm = int(round(session_state.tempo))
            key_info = f" | Live Key: {session_state.key_name} {session_state.scale_name}" if session_state.key_name else ""
            print(f"\n⚡ Synced with Ableton Live: {session_state.tempo:.1f} BPM ({session_state.time_signature}){key_info}")
            print(f"  Target: Track {target_track + 1} (idx {target_track}), Clip Slot {target_clip + 1} (idx {target_clip})")
        else:
            if target_track is None:
                target_track = 0
            if target_clip is None:
                target_clip = 0
            if bpm is None:
                bpm = 120
            print(f"\nℹ Ableton Live session sync offline (using Track {target_track + 1} [idx {target_track}], Clip Slot {target_clip + 1} [idx {target_clip}])")
    elif bpm is None:
        bpm = 120

    request = GenerationRequest(
        key_center=args.key,
        scale_type=args.scale_type,
        bpm=bpm,
        chords=chords,
        octave=args.octave,
        max_octave=args.max_octave,
        humanize=humanize,
        seed=args.seed,
        voice_lead=args.voice_lead,
        filename=args.filename,
    )

    if args.miditool_dict:
        import json
        payload = to_miditool_dict(request)
        print(json.dumps(payload, indent=2))
        return 0

    if args.to_ableton:
        client = AbletonClient()
        try:
            injected = client.inject_progression(
                request,
                track_index=target_track,
                clip_index=target_clip,
                fire=args.fire,
                sync_session=False,
            )
            print(f"\n✓ Injected directly into Ableton Live:")
            print(f"  Track:        Track {target_track + 1} (idx {target_track})")
            print(f"  Clip Slot:    Clip Slot {target_clip + 1} (idx {target_clip})")
            print(f"  Total Notes:  {injected['notes_count']}")
            print(f"  Duration:     {injected['total_beats']:.1f} beats")
            print(f"  Launched:     {'Yes' if args.fire else 'No'}")
        except Exception as e:
            print(f"Error injecting into Ableton Live: {e}", file=sys.stderr)
            return 1

    if args.stream:
        print(f"\n▶ Streaming live to MIDI port '{args.port}' ({request.bpm} BPM)...")
        if args.loop:
            print("  Looping continuously. Press Ctrl+C to stop.")
        try:
            stream_progression(request, port_name=args.port, loop=args.loop)
            print("✓ Finished streaming.")
        except KeyboardInterrupt:
            print("\n⏹ Stream stopped by user.")
        except Exception as e:
            print(f"Error streaming MIDI: {e}", file=sys.stderr)
            return 1

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
        f"  Details:  {args.key} {args.scale_type} | {request.bpm} BPM | {result.total_beats:.1f} beats total\n"
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
