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
