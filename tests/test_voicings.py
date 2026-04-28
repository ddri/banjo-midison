"""Tests for voicings.py."""

import pytest

from banjo.voicings import apply_voicing


class TestVoicings:
    # Cmaj7 in close position: C4 E4 G4 B4 = MIDI 60 64 67 71
    CMAJ7 = [60, 64, 67, 71]

    def test_close_is_passthrough_for_already_close(self):
        assert apply_voicing(list(self.CMAJ7), "close") == self.CMAJ7

    def test_drop2_drops_second_from_top(self):
        # 2nd from top is G4 (67) → drops to G3 (55)
        result = apply_voicing(list(self.CMAJ7), "drop2")
        assert sorted(result) == [55, 60, 64, 71]

    def test_drop3_drops_third_from_top(self):
        # 3rd from top is E4 (64) → drops to E3 (52)
        result = apply_voicing(list(self.CMAJ7), "drop3")
        assert sorted(result) == [52, 60, 67, 71]

    def test_drop2and4(self):
        # 2nd from top (G4=67) and 4th from top (C4=60) drop an octave
        result = apply_voicing(list(self.CMAJ7), "drop2and4")
        assert sorted(result) == [48, 55, 64, 71]

    def test_spread_drops_root(self):
        result = apply_voicing(list(self.CMAJ7), "spread")
        # Root C4 (60) becomes C3 (48)
        assert sorted(result) == [48, 64, 67, 71]

    def test_rootless_omits_root(self):
        result = apply_voicing(list(self.CMAJ7), "rootless")
        assert result == [64, 67, 71]
        assert len(result) == len(self.CMAJ7) - 1

    def test_unknown_voicing_raises(self):
        with pytest.raises(ValueError):
            apply_voicing(list(self.CMAJ7), "imaginary")

    def test_single_note_handled(self):
        # Edge case: voicing a single note shouldn't crash
        assert apply_voicing([60], "close") == [60]
        assert apply_voicing([60], "drop2") == [60]
        assert apply_voicing([60], "rootless") == [60]


class TestApplyVoicingPurity:
    """
    Voice leading depends on apply_voicing being a pure function of
    (notes, voicing). If this regresses, voice-leading determinism breaks
    silently. See spec: docs/superpowers/specs/2026-04-28-voice-leading-design.md
    """

    def test_same_input_same_output(self):
        notes = [60, 64, 67, 71]
        for voicing in ("close", "drop2", "drop3", "drop2and4", "spread", "rootless"):
            r1 = apply_voicing(list(notes), voicing)
            r2 = apply_voicing(list(notes), voicing)
            assert r1 == r2, f"apply_voicing({notes!r}, {voicing!r}) not deterministic"

    def test_input_not_mutated(self):
        notes = [60, 64, 67, 71]
        original = list(notes)
        for voicing in ("close", "drop2", "drop3", "drop2and4", "spread", "rootless"):
            apply_voicing(notes, voicing)
            assert notes == original, f"apply_voicing mutated input under voicing={voicing!r}"
