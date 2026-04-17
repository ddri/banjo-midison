"""
Test corpus generator.

Produces a curated set of .mid files that exercise the theory layer across
genres, modes, and harmonic devices. Drag the output into your DAW and
audition each file to verify the generator sounds correct.

Usage:
    banjo-corpus
    banjo-corpus --output-dir /custom/path
"""

from __future__ import annotations

import argparse
from pathlib import Path

from banjo.midi_writer import (
    ChordSpec,
    GenerationRequest,
    HumanizeSpec,
    generate,
)

DEFAULT_OUTPUT_DIR = Path.cwd() / "output"


def _basic_ii_v_i_major() -> GenerationRequest:
    return GenerationRequest(
        key_center="C",
        scale_type="major",
        bpm=110,
        chords=[
            ChordSpec("ii7", 4, voicing="close"),
            ChordSpec("V7", 4, voicing="close"),
            ChordSpec("Imaj7", 8, voicing="close"),
        ],
        octave=4,
        filename="01_ii-V-I_C_major_close",
        prompt_context="The most basic jazz cadence in C major, root-position close voicings.",
        generation_notes="A textbook ii-V-I — the foundation of jazz harmony.",
    )


def _neo_soul_F_extended() -> GenerationRequest:
    return GenerationRequest(
        key_center="F",
        scale_type="major",
        bpm=78,
        chords=[
            ChordSpec("Imaj9", 4, voicing="rootless"),
            ChordSpec("iii7", 4, voicing="rootless"),
            ChordSpec("vi11", 4, voicing="rootless"),
            ChordSpec("ii9", 4, voicing="rootless"),
        ],
        octave=4,
        humanize=HumanizeSpec(velocity_range=12, timing_ms=8, base_velocity=72),
        seed=42,
        filename="02_neo_soul_F_rootless",
        prompt_context="Neo-soul progression in F, rootless voicings — bassist would play roots.",
        generation_notes=(
            "Imaj9 → iii7 → vi11 → ii9. Rootless voicings put the 3rd in the bass of each "
            "chord, which is the defining sound of D'Angelo / Robert Glasper era piano comping. "
            "Light humanization for a played-in feel."
        ),
    )


def _neo_soul_Eb_with_subs() -> GenerationRequest:
    return GenerationRequest(
        key_center="Eb",
        scale_type="major",
        bpm=72,
        chords=[
            ChordSpec("Imaj9", 4, voicing="drop2"),
            ChordSpec("V7/vi", 2, voicing="drop2"),
            ChordSpec("vi9", 4, voicing="drop2"),
            ChordSpec("ii9", 2, voicing="drop2"),
            ChordSpec("V13", 2, voicing="drop2"),
            ChordSpec("Imaj9", 2, voicing="drop2"),
        ],
        octave=4,
        humanize=HumanizeSpec(velocity_range=10, base_velocity=75),
        seed=7,
        filename="03_neo_soul_Eb_secondary_dominant",
        prompt_context="Neo-soul in Eb with a secondary dominant approach to vi.",
        generation_notes=(
            "Imaj9 - V7/vi - vi9 - ii9 - V13 - Imaj9. The V7/vi (a C7 in the key of Eb) "
            "tonicizes the vi briefly before the standard ii-V-I lands. Drop-2 voicings "
            "give a slightly wider, more horn-like spread than close position."
        ),
    )


def _modal_mixture_major() -> GenerationRequest:
    return GenerationRequest(
        key_center="G",
        scale_type="major",
        bpm=92,
        chords=[
            ChordSpec("I", 4, voicing="close"),
            ChordSpec("bVII", 4, voicing="close"),
            ChordSpec("IV", 4, voicing="close"),
            ChordSpec("I", 4, voicing="close"),
        ],
        octave=4,
        filename="04_modal_mixture_G_bVII",
        prompt_context="Classic I-bVII-IV-I rock/folk progression in G.",
        generation_notes=(
            "The bVII (F major in G) is borrowed from G mixolydian — the defining "
            "harmonic move in countless rock and folk songs. Should sound like every "
            "campfire song you've ever heard."
        ),
    )


def _dorian_groove() -> GenerationRequest:
    return GenerationRequest(
        key_center="D",
        scale_type="dorian",
        bpm=96,
        chords=[
            ChordSpec("i9", 4, voicing="rootless"),
            ChordSpec("IV9", 4, voicing="rootless"),
            ChordSpec("i9", 4, voicing="rootless"),
            ChordSpec("IV9", 4, voicing="rootless"),
        ],
        octave=4,
        humanize=HumanizeSpec(velocity_range=8, base_velocity=78),
        seed=23,
        filename="05_dorian_D_groove",
        prompt_context="D dorian groove, i9 to IV9 vamp.",
        generation_notes=(
            "Dorian's signature is the major IV chord (G major in D dorian) against the "
            "minor tonic. Two-chord vamp at 96 BPM — think 'So What' or any modal jazz "
            "head. Rootless voicings keep it light."
        ),
    )


def _minor_with_secondary() -> GenerationRequest:
    return GenerationRequest(
        key_center="A",
        scale_type="minor",
        bpm=84,
        chords=[
            ChordSpec("i7", 4, voicing="close"),
            ChordSpec("V7/iv", 4, voicing="close"),
            ChordSpec("iv7", 4, voicing="close"),
            ChordSpec("V7", 4, voicing="close"),
        ],
        octave=4,
        filename="06_minor_A_secondary_to_iv",
        prompt_context="A minor with a secondary dominant approaching the iv.",
        generation_notes=(
            "Am7 - A7 - Dm7 - E7. The A7 (V7/iv) momentarily tonicizes Dm before resolving. "
            "Standard minor-key device; the major-third in the V7/iv is what creates the "
            "harmonic surprise."
        ),
    )


def _altered_dominant() -> GenerationRequest:
    return GenerationRequest(
        key_center="C",
        scale_type="major",
        bpm=100,
        chords=[
            ChordSpec("ii9", 4, voicing="drop2"),
            ChordSpec("V7b9", 4, voicing="drop2"),
            ChordSpec("Imaj7", 8, voicing="drop2"),
        ],
        octave=4,
        filename="07_altered_dominant_C",
        prompt_context="ii-V-I with a b9 alteration on the dominant.",
        generation_notes=(
            "Dm9 - G7b9 - Cmaj7. The b9 on the dominant is the most common alteration in "
            "jazz; creates a sharper, more urgent pull to the tonic than a plain V7."
        ),
    )


def _spread_voicing_test() -> GenerationRequest:
    return GenerationRequest(
        key_center="C",
        scale_type="major",
        bpm=80,
        chords=[
            ChordSpec("Imaj9", 4, voicing="spread"),
            ChordSpec("vi9", 4, voicing="spread"),
            ChordSpec("ii9", 4, voicing="spread"),
            ChordSpec("V13", 4, voicing="spread"),
        ],
        octave=4,
        filename="08_spread_voicing_C",
        prompt_context="Spread voicings to verify the wider-spacing transformation.",
        generation_notes=(
            "Same chords as a typical I-vi-ii-V but with the root dropped an octave. "
            "Useful for piano LH/RH separation or guitar fingerstyle arrangements."
        ),
    )


def _mixolydian_funk() -> GenerationRequest:
    return GenerationRequest(
        key_center="E",
        scale_type="mixolydian",
        bpm=104,
        chords=[
            ChordSpec("I7", 4, voicing="close"),
            ChordSpec("bVII", 2, voicing="close"),
            ChordSpec("IV", 2, voicing="close"),
            ChordSpec("I7", 4, voicing="close"),
            ChordSpec("v7", 4, voicing="close"),
        ],
        octave=4,
        humanize=HumanizeSpec(velocity_range=10, base_velocity=82),
        seed=99,
        filename="09_mixolydian_E_funk",
        prompt_context="E mixolydian funk vamp.",
        generation_notes=(
            "I7 - bVII - IV - I7 - v7. Mixolydian's flat-7 makes the I a dominant 7 chord "
            "(E7), and the minor v (Bm7) is mode-defining. Funk/blues territory."
        ),
    )


def _half_diminished_minor() -> GenerationRequest:
    return GenerationRequest(
        key_center="D",
        scale_type="minor",
        bpm=88,
        chords=[
            ChordSpec("i7", 4, voicing="close"),
            ChordSpec("iiø", 4, voicing="close"),
            ChordSpec("V7b9", 4, voicing="close"),
            ChordSpec("i7", 4, voicing="close"),
        ],
        octave=4,
        filename="10_minor_iiø_V7b9_i_D",
        prompt_context="Minor ii-V-i with half-diminished ii.",
        generation_notes=(
            "Dm7 - Em7b5 - A7b9 - Dm7. The half-diminished ii (Em7b5) is the standard "
            "minor-key ii chord; pairing it with a V7b9 gives the classic minor-jazz "
            "cadence."
        ),
    )


def _drop2and4_voicing_test() -> GenerationRequest:
    return GenerationRequest(
        key_center="Bb",
        scale_type="major",
        bpm=90,
        chords=[
            ChordSpec("Imaj7", 4, voicing="drop2and4"),
            ChordSpec("vi7", 4, voicing="drop2and4"),
            ChordSpec("ii7", 4, voicing="drop2and4"),
            ChordSpec("V7", 4, voicing="drop2and4"),
        ],
        octave=4,
        filename="11_drop2and4_Bb",
        prompt_context="Drop-2-and-4 voicings to verify the transformation.",
        generation_notes=(
            "Bbmaj7 - Gm7 - Cm7 - F7. Drop-2-and-4 spreads the chord across two octaves, "
            "common in big band brass/sax voicings."
        ),
    )


def _chromatic_descent() -> GenerationRequest:
    return GenerationRequest(
        key_center="C",
        scale_type="major",
        bpm=76,
        chords=[
            ChordSpec("Imaj7", 4, voicing="close"),
            ChordSpec("bIIImaj7", 4, voicing="close"),
            ChordSpec("bVImaj7", 4, voicing="close"),
            ChordSpec("bIImaj7", 4, voicing="close"),
        ],
        octave=4,
        filename="12_modal_mixture_C_chromatic",
        prompt_context="Chromatic mediant / modal mixture descent in C.",
        generation_notes=(
            "Cmaj7 - Ebmaj7 - Abmaj7 - Dbmaj7. Heavy modal mixture; the bIII, bVI, and "
            "bII are all borrowed from C minor / phrygian. Common in cinematic and "
            "neo-soul ballad writing."
        ),
    )


CORPUS = [
    _basic_ii_v_i_major,
    _neo_soul_F_extended,
    _neo_soul_Eb_with_subs,
    _modal_mixture_major,
    _dorian_groove,
    _minor_with_secondary,
    _altered_dominant,
    _spread_voicing_test,
    _mixolydian_funk,
    _half_diminished_minor,
    _drop2and4_voicing_test,
    _chromatic_descent,
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the banjo test corpus.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    print(f"Writing test corpus to: {output_dir}")

    for builder in CORPUS:
        request = builder()
        result = generate(request, output_dir)
        print(f"  ✓ {result.filepath.name}  ({len(result.resolved)} chords, {result.total_beats} beats)")

    print(f"\nDone. {len(CORPUS)} files written.")
    print("Drag them into your DAW and audition each one to validate the theory layer.")


if __name__ == "__main__":
    main()
