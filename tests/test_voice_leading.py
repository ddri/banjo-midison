"""Tests for voice_leading.py."""

import pytest

from banjo.theory import parse_roman_numeral, parse_pitch_class
from banjo.voice_leading import _voicing_distance, choose_voicing_position, build_candidates


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
        inv_idx, result = choose_voicing_position([[67, 71, 74]], [60, 64, 67])
        assert inv_idx == 0
        assert sorted(result) == [55, 59, 62]

    def test_picks_lowest_scoring_inversion_worked_example(self):
        # Worked example from spec: I -> V in C, all close
        # root: [67,71,74] -> best k=-1 -> [55,59,62] score 8
        # 1st inv: [71,74,79] -> best k=-1 -> [59,62,67] score 3 <- winner
        # 2nd inv: [62,67,71] -> best k=0 score 6
        candidates = [[67, 71, 74], [71, 74, 79], [62, 67, 71]]
        inv_idx, result = choose_voicing_position(candidates, [60, 64, 67])
        assert inv_idx == 1  # 1st inv wins (the worked example)
        assert sorted(result) == [59, 62, 67]

    def test_tie_break_prefers_smaller_abs_k(self):
        # previous=[60, 72], candidate=[[66]]
        # k=0: [66] -> min(6,6) = 6
        # k=-1: [54] -> min(6,18) = 6
        # k=+1: [78] -> min(18,6) = 6
        # All k tie. Smaller |k| wins -> k=0 -> [66]
        inv_idx, result = choose_voicing_position([[66]], [60, 72])
        assert inv_idx == 0
        assert result == [66]

    def test_tie_break_prefers_smaller_inversion_index(self):
        # Two candidates that both score 0 at k=0:
        # cand 0: [60] -> at k=0 vs previous [60], distance 0
        # cand 1: [60, 60] -> at k=0 vs previous [60], distance 0 (both 60s pick prev[0]=60)
        # Both reach score 0 at k=0. Tie-keys: (0,0,0) vs (1,0,0). Idx 0 wins.
        # The result is [60] (length 1), proving idx 0 was picked, not idx 1
        # (which would have returned [60, 60], length 2).
        inv_idx, result = choose_voicing_position([[60], [60, 60]], [60])
        assert inv_idx == 0
        assert result == [60]

    def test_tie_break_signed_k_when_abs_k_ties(self):
        # previous=[60, 84]; candidate=[[72]]:
        # k=0: [72] -> min(12, 12) = 12
        # k=-1: [60] -> min(0, 24) = 0  <- best
        # k=+1: [84] -> min(24, 0) = 0  <- ties best
        # Tie at 0. |k|=1 for both. Signed k smaller -> k=-1 -> [60].
        inv_idx, result = choose_voicing_position([[72]], [60, 84])
        assert inv_idx == 0
        assert result == [60]


class TestBuildCandidates:
    def test_triad_close_voicing_yields_three_inversions(self):
        # I in C major, close voicing, no explicit inversion -> 3 candidates
        parsed = parse_roman_numeral("I")
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="close", explicit_inversion=False,
        )
        assert len(candidates) == 3
        # Inversion 0: [60, 64, 67] (root position)
        assert sorted(candidates[0]) == [60, 64, 67]

    def test_seventh_chord_yields_four_inversions(self):
        # I7 in C major, close voicing -> 4 candidates (root, 1st, 2nd, 3rd)
        parsed = parse_roman_numeral("I7")
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="close", explicit_inversion=False,
        )
        assert len(candidates) == 4

    def test_thirteenth_chord_capped_at_four_inversions(self):
        # V13 has 7 notes; cap = min(3, N-1) = min(3, 6) = 3, so 4 candidates
        parsed = parse_roman_numeral("V13")
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="close", explicit_inversion=False,
        )
        assert len(candidates) == 4
        # Bottom note pitch class of every candidate must be a chord tone (R/3/5/7)
        # of V in C: G=7, B=11, D=2, F=5
        for cand in candidates:
            assert min(cand) % 12 in {7, 11, 2, 5}

    def test_rootless_seventh_yields_three_candidates(self):
        # I7 rootless: N (post-voicing) = 3, so candidates {0, 1, 2}
        parsed = parse_roman_numeral("I7")
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="rootless", explicit_inversion=False,
        )
        assert len(candidates) == 3
        # Each candidate has 3 notes (root dropped after inversion)
        for cand in candidates:
            assert len(cand) == 3

    def test_explicit_inversion_yields_single_candidate(self):
        # V64 with explicit_inversion=True -> candidate set is {2} only
        parsed = parse_roman_numeral("V64")  # parses to inversion 2
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="close", explicit_inversion=True,
        )
        assert len(candidates) == 1
        # V at 2nd inversion close = D-G-B = [74, 79, 83]
        assert sorted(candidates[0]) == [74, 79, 83]
