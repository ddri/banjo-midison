"""Tests for voice_leading.py."""

import pytest

from banjo.voice_leading import _voicing_distance, choose_voicing_position


class TestVoicingDistance:
    def test_zero_when_chords_identical(self):
        assert _voicing_distance([60, 64, 67], [60, 64, 67]) == 0

    def test_nearest_neighbor_sums_minimum_distances(self):
        # candidate=[59, 62, 67], previous=[60, 64, 67]
        # 59 -> 60 (dist 1), 62 -> 60 or 64 (dist 2 either way), 67 -> 67 (dist 0)
        assert _voicing_distance([59, 62, 67], [60, 64, 67]) == 3

    def test_asymmetric_two_notes_can_share_neighbor(self):
        # Both 60s pick 60 as nearest -> total distance 0
        assert _voicing_distance([60, 60], [60, 80]) == 0

    def test_handles_voice_count_mismatch(self):
        # 4 candidate notes vs 3 previous notes; just sums per-candidate-note minima
        # 60 -> 60 (0), 64 -> 64 (0), 67 -> 67 (0), 70 -> 67 (3) = 3
        assert _voicing_distance([60, 64, 67, 70], [60, 64, 67]) == 3


class TestChooseVoicingPosition:
    def test_picks_optimal_k_for_single_inversion(self):
        # Previous: I close [60, 64, 67]
        # Candidate: V root close [67, 71, 74]
        # k=0: 0+4+7 = 11; k=-1: [55,59,62] -> 5+1+2 = 8
        # k=-1 wins
        result = choose_voicing_position([[67, 71, 74]], [60, 64, 67])
        assert sorted(result) == [55, 59, 62]

    def test_picks_lowest_scoring_inversion_worked_example(self):
        # Worked example from spec: I -> V in C, all close
        # root: [67,71,74] -> best k=-1 -> [55,59,62] score 8
        # 1st inv: [71,74,79] -> best k=-1 -> [59,62,67] score 3 <- winner
        # 2nd inv: [62,67,71] -> best k=0 score 6
        candidates = [[67, 71, 74], [71, 74, 79], [62, 67, 71]]
        result = choose_voicing_position(candidates, [60, 64, 67])
        assert sorted(result) == [59, 62, 67]

    def test_tie_break_prefers_smaller_abs_k(self):
        # previous=[60, 72], candidate=[[66]]
        # k=0: [66] -> min(6,6) = 6
        # k=-1: [54] -> min(6,18) = 6
        # k=+1: [78] -> min(18,6) = 6
        # All k tie. Smaller |k| wins -> k=0 -> [66]
        result = choose_voicing_position([[66]], [60, 72])
        assert result == [66]

    def test_tie_break_prefers_smaller_inversion_index(self):
        # Two candidates that both score 0 at k=0:
        # cand 0: [60] -> at k=0 vs previous [60], distance 0
        # cand 1: [60, 60] -> at k=0 vs previous [60], distance 0 (both 60s pick prev[0]=60)
        # Both reach score 0 at k=0. Tie-keys: (0,0,0) vs (1,0,0). Idx 0 wins.
        # The result is [60] (length 1), proving idx 0 was picked, not idx 1
        # (which would have returned [60, 60], length 2).
        result = choose_voicing_position([[60], [60, 60]], [60])
        assert result == [60]

    def test_tie_break_signed_k_when_abs_k_ties(self):
        # previous=[60, 84]; candidate=[[72]]:
        # k=0: [72] -> min(12, 12) = 12
        # k=-1: [60] -> min(0, 24) = 0  <- best
        # k=+1: [84] -> min(24, 0) = 0  <- ties best
        # Tie at 0. |k|=1 for both. Signed k smaller -> k=-1 -> [60].
        result = choose_voicing_position([[72]], [60, 84])
        assert result == [60]
