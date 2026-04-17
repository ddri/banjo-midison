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
