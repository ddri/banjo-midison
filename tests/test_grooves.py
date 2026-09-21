"""Unit tests for the grooves module."""

from __future__ import annotations

import pytest

from banjo.grooves import (
    get_groove,
    list_grooves,
    select_voices,
    tile_groove_pulses,
)


class TestGrooves:
    def test_list_grooves_contains_all_core_styles(self):
        grooves = set(list_grooves())
        expected = {
            "block",
            "strum",
            "arpeggio_up",
            "arpeggio_down",
            "comp_syncopated",
            "charleston",
            "four_on_floor",
            "bossa",
            "tresillo",
            "reggae_skank",
            "waltz",
        }
        assert expected.issubset(grooves)

    def test_get_groove_success(self):
        charleston = get_groove("charleston")
        assert charleston.name == "charleston"
        assert charleston.meter_beats == 4.0
        assert len(charleston.pulses) == 2
        # Beat 1 (0.0) and "and" of 2 (1.5)
        assert charleston.pulses[0].beat_offset == 0.0
        assert charleston.pulses[1].beat_offset == 1.5

    def test_get_groove_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown pattern/groove"):
            get_groove("polka_blaster")

    def test_tile_groove_pulses_block(self):
        block = get_groove("block")
        pulses = tile_groove_pulses(block, 6.0)
        assert len(pulses) == 1
        assert pulses[0].beat_offset == 0.0
        assert pulses[0].duration_beats == 6.0

    def test_tile_groove_pulses_tiling(self):
        charleston = get_groove("charleston")
        # 4 beats -> 2 pulses
        p4 = tile_groove_pulses(charleston, 4.0)
        assert len(p4) == 2

        # 8 beats -> 4 pulses (cycles twice)
        p8 = tile_groove_pulses(charleston, 8.0)
        assert len(p8) == 4
        assert [p.beat_offset for p in p8] == [0.0, 1.5, 4.0, 5.5]

    def test_tile_groove_pulses_clamping(self):
        four = get_groove("four_on_floor")
        # 2.2 beats: hits at 0.0, 1.0, 2.0 (pulse at 2.0 has duration clamped to 0.2)
        pulses = tile_groove_pulses(four, 2.2)
        assert len(pulses) == 3
        assert pulses[2].beat_offset == 2.0
        assert pulses[2].duration_beats == pytest.approx(0.2)

    def test_select_voices_all(self):
        notes = [48, 52, 55, 59]
        assert select_voices(notes, "all") == [48, 52, 55, 59]

    def test_select_voices_bass(self):
        notes = [48, 52, 55, 59]
        assert select_voices(notes, "bass") == [48]

    def test_select_voices_upper(self):
        notes = [48, 52, 55, 59]
        assert select_voices(notes, "upper") == [52, 55, 59]

    def test_select_voices_single_note(self):
        notes = [60]
        assert select_voices(notes, "bass") == [60]
        assert select_voices(notes, "upper") == [60]
        assert select_voices(notes, "all") == [60]

    def test_bossa_groove_voices(self):
        bossa = get_groove("bossa")
        assert any(p.voice_target == "bass" for p in bossa.pulses)
        assert any(p.voice_target == "upper" for p in bossa.pulses)
