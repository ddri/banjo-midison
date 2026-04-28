"""Integration tests for midi_writer.py."""

from pathlib import Path

import mido
import pytest

from banjo.midi_writer import (
    ChordSpec,
    GenerationRequest,
    HumanizeSpec,
    generate,
)


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    return tmp_path / "midi"


class TestMidiWriter:
    def test_basic_generation_creates_files(self, tmp_output: Path):
        request = GenerationRequest(
            key_center="C",
            scale_type="major",
            bpm=120,
            chords=[
                ChordSpec("I", 4),
                ChordSpec("V", 4),
            ],
            filename="test_basic",
        )
        result = generate(request, tmp_output)

        assert result.filepath.exists()
        assert result.sidecar_path.exists()
        assert result.filepath.suffix == ".mid"
        assert result.sidecar_path.suffix == ".md"
        assert len(result.resolved) == 2

    def test_midi_file_is_valid(self, tmp_output: Path):
        request = GenerationRequest(
            key_center="C",
            scale_type="major",
            bpm=100,
            chords=[ChordSpec("Imaj7", 4)],
            filename="test_valid",
        )
        result = generate(request, tmp_output)

        # mido should be able to read it back
        mid = mido.MidiFile(result.filepath)
        assert mid.ticks_per_beat == 480

        # Should contain note_on events
        note_ons = [
            msg for track in mid.tracks for msg in track
            if msg.type == "note_on" and msg.velocity > 0
        ]
        assert len(note_ons) == 4  # Cmaj7 has 4 notes

    def test_sidecar_contains_metadata(self, tmp_output: Path):
        request = GenerationRequest(
            key_center="F",
            scale_type="major",
            bpm=78,
            chords=[ChordSpec("Imaj9", 4, voicing="rootless")],
            filename="test_sidecar",
            prompt_context="User asked for a neo-soul vibe.",
            generation_notes="Rootless voicing keeps it light.",
        )
        result = generate(request, tmp_output)

        content = result.sidecar_path.read_text()
        assert "User asked for a neo-soul vibe." in content
        assert "Rootless voicing keeps it light." in content
        assert "F major" in content
        assert "78 BPM" in content
        assert "Imaj9" in content

    def test_seed_is_reproducible(self, tmp_output: Path):
        """Same seed + same humanization should produce identical files."""
        def make_request(seed: int) -> GenerationRequest:
            return GenerationRequest(
                key_center="C",
                scale_type="major",
                bpm=100,
                chords=[ChordSpec("I", 4), ChordSpec("V", 4)],
                humanize=HumanizeSpec(velocity_range=20, timing_ms=10),
                seed=seed,
                filename=f"test_seed_{seed}",
            )

        r1 = generate(make_request(42), tmp_output / "a")
        r2 = generate(make_request(42), tmp_output / "b")

        # Compare velocities of note_on events
        def velocities(path: Path) -> list[int]:
            mid = mido.MidiFile(path)
            return [
                msg.velocity for track in mid.tracks for msg in track
                if msg.type == "note_on" and msg.velocity > 0
            ]

        assert velocities(r1.filepath) == velocities(r2.filepath)

    def test_total_beats_accumulated_correctly(self, tmp_output: Path):
        request = GenerationRequest(
            key_center="C",
            scale_type="major",
            bpm=100,
            chords=[
                ChordSpec("I", 2),
                ChordSpec("vi", 2),
                ChordSpec("ii", 2),
                ChordSpec("V", 2),
            ],
            filename="test_beats",
        )
        result = generate(request, tmp_output)
        assert result.total_beats == 8

    def test_inversion_override(self, tmp_output: Path):
        """ChordSpec.inversion should override the parsed numeral's inversion."""
        request = GenerationRequest(
            key_center="C",
            scale_type="major",
            bpm=100,
            chords=[ChordSpec("I", 4, inversion=1)],  # First inversion
            filename="test_inv",
        )
        result = generate(request, tmp_output)
        # Lowest note should be E (pitch class 4), not C
        first_chord_midi = result.resolved[0]["midi"]
        assert min(first_chord_midi) % 12 == 4


class TestVoiceLead:
    def test_voice_lead_defaults_false_unchanged_behavior(self, tmp_path):
        # Without voice_lead, V after I lands at root position close = [67, 71, 74]
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V", duration_beats=4),
            ],
        )
        result = generate(request, tmp_path)
        assert sorted(result.resolved[1]["midi"]) == [67, 71, 74]

    def test_voice_lead_true_picks_smoothest_inversion(self, tmp_path):
        # Worked example: I -> V with voice_lead lands V at 1st inv, k=-1: [59,62,67]
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        assert sorted(result.resolved[1]["midi"]) == [59, 62, 67]

    def test_first_chord_unchanged_with_voice_lead(self, tmp_path):
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        spec = ChordSpec(numeral="I", duration_beats=4, voicing="close")
        off = generate(
            GenerationRequest(key_center="C", scale_type="major", bpm=120, chords=[spec]),
            tmp_path / "off",
        )
        on = generate(
            GenerationRequest(
                key_center="C", scale_type="major", bpm=120, chords=[spec],
                voice_lead=True,
            ),
            tmp_path / "on",
        )
        assert off.resolved[0]["midi"] == on.resolved[0]["midi"]

    def test_voicing_preservation_drop2_keeps_wide_gap(self, tmp_path):
        """
        Strongest correctness signal in the suite: if the inversion+k
        expansion ever shifts individual notes instead of the whole chord,
        drop2's signature wide span collapses.

        We check total span (highest - lowest), not max adjacent gap.
        Drop2 of a 4-note close chord always produces span >= 12 semitones
        because the 2nd-from-top voice moves an octave below the rest.
        Close-position 7th chords have span <= 11 semitones, so this
        threshold cleanly distinguishes drop2 from accidental flattening.
        Octave shifts (k) preserve span, so this holds under voice leading.

        If this test fails, the pipeline order
        (build_chord -> apply_voicing -> shift) is wrong.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I7", duration_beats=4, voicing="drop2"),
                ChordSpec(numeral="vi7", duration_beats=4, voicing="drop2"),
                ChordSpec(numeral="ii7", duration_beats=4, voicing="drop2"),
                ChordSpec(numeral="V7", duration_beats=4, voicing="drop2"),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        for chord in result.resolved:
            notes = sorted(chord["midi"])
            span = notes[-1] - notes[0]
            assert span >= 12, (
                f"drop2 voicing collapsed for {chord['numeral']}: "
                f"notes={notes}, span={span}. Expected span >= 12 (drop2 "
                f"puts the 2nd-from-top voice an octave below the rest). "
                f"Pipeline is likely shifting individual notes instead of "
                f"the whole chord."
            )

    def test_explicit_inversion_pinned_but_k_still_optimized(self, tmp_path):
        """
        V64 with voice_lead on: inversion stays 2 AND k is the score-optimizing
        choice among the 5 candidates at that inversion. If a regression pins
        k=0 when inversion is explicit, this test catches it.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V64", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        v_notes = sorted(result.resolved[1]["midi"])
        # V at 2nd inv close (octave=4) = [74, 79, 83]. Previous = [60, 64, 67].
        # build_candidates returns one candidate (inversion pinned to 2);
        # choose_voicing_position then picks k:
        #   k=0  [74,79,83]: 7+12+16 = 35
        #   k=-1 [62,67,71]: 2+0+4   = 6  <- winner
        #   k=-2 [50,55,59]: 10+5+1  = 16
        # k=-1 wins. Inversion stayed at 2 (pinned), but k was still optimized.
        assert v_notes == [62, 67, 71]
        # Inversion preserved: pitch classes are D-G-B = {2, 7, 11}
        assert sorted(set(n % 12 for n in v_notes)) == [2, 7, 11]

    def test_v13_never_lands_with_extension_in_bass(self, tmp_path):
        """V13's bass note must be a chord tone (R/3/5/7), never an extension (9/11/13)."""
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V13", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        bottom_pc = min(result.resolved[1]["midi"]) % 12
        # V in C: chord tones are G(7), B(11), D(2), F(5).
        # Extensions: A(9), C(0), E(4) - these must NOT be the bass.
        assert bottom_pc in {7, 11, 2, 5}, (
            f"V13 landed with pc {bottom_pc} in bass; expected a chord tone (7,11,2,5)"
        )

    def test_rootless_after_close_does_not_crash(self, tmp_path):
        """
        Mixing voice counts across chords (close=4 voices, rootless 7th=3 voices)
        should still produce a sensible result. Voice leading only compares
        candidates of the *same* chord, so the cross-chord count mismatch is
        only a sanity check that nothing blows up.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I7", duration_beats=4, voicing="close"),
                ChordSpec(numeral="ii7", duration_beats=4, voicing="rootless"),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        # rootless of ii7 -> 3 notes
        assert len(result.resolved[1]["midi"]) == 3

    def test_register_stability_chromatic_mediant_chain(self, tmp_path):
        """
        Empirical bound: under a chromatic-mediant chain (large root motion,
        sympathetic to runaway drift), the lowest note across all chords stays
        within +/-12 semitones of the starting chord. Not algorithmically
        guaranteed; the score function naturally prefers smaller |k|.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="bIII", duration_beats=4),
                ChordSpec(numeral="bVI", duration_beats=4),
                ChordSpec(numeral="III", duration_beats=4),
                ChordSpec(numeral="I", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        starting_lowest = min(result.resolved[0]["midi"])
        for chord in result.resolved:
            lowest = min(chord["midi"])
            assert abs(lowest - starting_lowest) <= 12, (
                f"Chord {chord['numeral']} drifted to lowest={lowest} "
                f"from start={starting_lowest}"
            )

    def test_voice_lead_is_deterministic(self, tmp_path):
        """Same input twice -> identical resolved metadata, byte-for-byte."""
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate

        def make_request():
            return GenerationRequest(
                key_center="C", scale_type="major", bpm=120,
                chords=[
                    ChordSpec(numeral="I", duration_beats=4),
                    ChordSpec(numeral="vi", duration_beats=4),
                    ChordSpec(numeral="IV", duration_beats=4),
                    ChordSpec(numeral="V", duration_beats=4),
                ],
                voice_lead=True,
            )

        r1 = generate(make_request(), tmp_path / "a")
        r2 = generate(make_request(), tmp_path / "b")
        for c1, c2 in zip(r1.resolved, r2.resolved):
            assert c1["midi"] == c2["midi"]

    def test_chordspec_inversion_field_pins_inversion(self, tmp_path):
        """
        ChordSpec.inversion=1 explicitly forces 1st inversion even when root
        would score lower. Distinct from V64 (which encodes inversion in the
        numeral string); this test guards the second source of explicit-
        inversion intent.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="vi", duration_beats=4),
                ChordSpec(numeral="V", duration_beats=4, inversion=1),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        v_notes = sorted(result.resolved[1]["midi"])
        # Previous (vi close) = [69, 72, 76]. V 1st inv close = B-D-G = [71, 74, 79].
        # k=0 score = 1+2+3 = 6; k=-1 score = 10+7+2 = 19; k=+1 score = 7+10+15 = 32.
        # k=0 wins among the inversion=1 candidates -> [71, 74, 79].
        # (Unrestricted, V root k=0 [67,71,74] would score 2+1+2 = 5 and win;
        # the inversion=1 must override that.)
        assert v_notes == [71, 74, 79]
        # Pitch classes are B-D-G = {2, 7, 11} (1st inversion preserved)
        assert sorted(set(n % 12 for n in v_notes)) == [2, 7, 11]

    def test_resolved_metadata_reports_chosen_inversion(self, tmp_path):
        """
        When voice leading picks a non-root inversion, the resolved metadata's
        'inversion' field must report the actual chosen value, not the original
        parse value. Regression test for a bug where inversion always read 0
        on the voice-led path.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        # Worked example: V lands at 1st inversion (k=-1, [59,62,67]).
        assert result.resolved[1]["inversion"] == 1
        # And the chord-1 metadata is unchanged (inv 0 since I is in root position).
        assert result.resolved[0]["inversion"] == 0

    def test_chordspec_inversion_zero_is_treated_as_explicit(self, tmp_path):
        """
        Passing ChordSpec.inversion=0 is treated as explicit (user names root
        deliberately, per the MCP schema's "omit this if you don't want to
        override" guidance). Without it, voice leading would pick 1st inversion
        at k=-1 (the worked example, score 3). With it, only root candidates
        are searched, and the optimizer picks k=-1 [55,59,62] score 8.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V", duration_beats=4, inversion=0),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        v_notes = sorted(result.resolved[1]["midi"])
        # V root close at octave 4 = [67, 71, 74]. Previous = [60, 64, 67].
        # k=0  [67,71,74]: 0+4+7 = 11
        # k=-1 [55,59,62]: 5+1+2 = 8  <- winner among root candidates
        # k=-2 [43,47,50]: 17+13+10 = 40
        # Inversion stayed at 0 (root); k=-1 chosen for register match.
        assert v_notes == [55, 59, 62]
        # Pitch classes G-B-D (root in bass)
        assert sorted(set(n % 12 for n in v_notes)) == [2, 7, 11]
        # Verify the bass note IS the root (G = pc 7), not 3rd or 5th
        assert min(v_notes) % 12 == 7
