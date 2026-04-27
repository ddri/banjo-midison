"""Tests for voice_leading.py."""

import pytest

from banjo.voice_leading import _voicing_distance


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
