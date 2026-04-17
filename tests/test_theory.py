"""Tests for theory.py: parser, scale generation, chord building."""

from __future__ import annotations

import pytest

from banjo.theory import (
    QUALITY_AUGMENTED,
    QUALITY_DIMINISHED,
    QUALITY_MAJOR,
    QUALITY_MINOR,
    build_chord,
    midi_note_name,
    parse_pitch_class,
    parse_roman_numeral,
    pitch_class_name,
    scale_pitch_classes,
)


# ---------------------------------------------------------------------------
# Pitch class basics
# ---------------------------------------------------------------------------

class TestPitchClass:
    def test_natural_notes(self):
        assert parse_pitch_class("C") == 0
        assert parse_pitch_class("D") == 2
        assert parse_pitch_class("E") == 4
        assert parse_pitch_class("F") == 5
        assert parse_pitch_class("G") == 7
        assert parse_pitch_class("A") == 9
        assert parse_pitch_class("B") == 11

    def test_sharps_and_flats(self):
        assert parse_pitch_class("C#") == 1
        assert parse_pitch_class("Db") == 1
        assert parse_pitch_class("F#") == 6
        assert parse_pitch_class("Gb") == 6
        assert parse_pitch_class("Bb") == 10
        assert parse_pitch_class("A#") == 10

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            parse_pitch_class("H")

    def test_midi_note_name(self):
        assert midi_note_name(60) == "C4"     # middle C
        assert midi_note_name(69) == "A4"     # A440
        assert midi_note_name(48) == "C3"
        assert midi_note_name(72) == "C5"


# ---------------------------------------------------------------------------
# Scales
# ---------------------------------------------------------------------------

class TestScales:
    def test_c_major(self):
        assert scale_pitch_classes(0, "major") == (0, 2, 4, 5, 7, 9, 11)

    def test_a_minor(self):
        assert scale_pitch_classes(9, "minor") == (9, 11, 0, 2, 4, 5, 7)

    def test_d_dorian(self):
        # D dorian shares notes with C major but starts on D.
        assert scale_pitch_classes(2, "dorian") == (2, 4, 5, 7, 9, 11, 0)

    def test_e_mixolydian(self):
        # E mix: E F# G# A B C# D
        assert scale_pitch_classes(4, "mixolydian") == (4, 6, 8, 9, 11, 1, 2)


# ---------------------------------------------------------------------------
# Roman numeral parsing
# ---------------------------------------------------------------------------

class TestNumeralParsing:
    def test_basic_major_triad(self):
        p = parse_roman_numeral("I")
        assert p.degree == 1
        assert p.quality == QUALITY_MAJOR
        assert p.extensions == ()
        assert p.inversion == 0
        assert p.accidental == 0
        assert p.secondary_of is None

    def test_basic_minor_triad(self):
        p = parse_roman_numeral("vi")
        assert p.degree == 6
        assert p.quality == QUALITY_MINOR

    def test_diminished(self):
        p = parse_roman_numeral("vii°")
        assert p.degree == 7
        assert p.quality == QUALITY_DIMINISHED

        p2 = parse_roman_numeral("viio")
        assert p2.quality == QUALITY_DIMINISHED

    def test_augmented(self):
        p = parse_roman_numeral("III+")
        assert p.degree == 3
        assert p.quality == QUALITY_AUGMENTED

    def test_seventh(self):
        p = parse_roman_numeral("V7")
        assert p.degree == 5
        assert p.quality == QUALITY_MAJOR
        assert 7 in p.extensions

    def test_maj7(self):
        p = parse_roman_numeral("Imaj7")
        assert p.quality == QUALITY_MAJOR
        # The maj7 sentinel (-7) flags major-seventh interval
        assert -7 in p.extensions
        assert 7 in p.extensions

    def test_extensions_imply_lower(self):
        """ii9 should imply both 7 and 9 are in the chord."""
        p = parse_roman_numeral("ii9")
        assert 7 in p.extensions
        assert 9 in p.extensions

    def test_thirteenth_implies_seventh(self):
        p = parse_roman_numeral("V13")
        assert 7 in p.extensions
        assert 13 in p.extensions

    def test_alteration_b9(self):
        p = parse_roman_numeral("V7b9")
        assert "b9" in p.alterations

    def test_alteration_sharp11(self):
        p = parse_roman_numeral("Imaj7#11")
        assert "#11" in p.alterations

    def test_modal_mixture_flat_seven(self):
        p = parse_roman_numeral("bVII")
        assert p.degree == 7
        assert p.accidental == -1
        assert p.quality == QUALITY_MAJOR

    def test_modal_mixture_flat_three(self):
        p = parse_roman_numeral("bIII")
        assert p.degree == 3
        assert p.accidental == -1

    def test_secondary_dominant(self):
        p = parse_roman_numeral("V/vi")
        assert p.degree == 5
        assert p.secondary_of == 6

    def test_secondary_dominant_with_seventh(self):
        p = parse_roman_numeral("V7/ii")
        assert p.degree == 5
        assert 7 in p.extensions
        assert p.secondary_of == 2

    def test_half_diminished(self):
        p = parse_roman_numeral("iiø")
        assert p.quality == QUALITY_DIMINISHED
        assert 7 in p.extensions  # ø implies a 7

    def test_explicit_minor_marker(self):
        """ivm9 should be minor with 7+9 extensions (the 'm' is redundant for lowercase)."""
        p = parse_roman_numeral("ivm9")
        assert p.quality == QUALITY_MINOR
        assert 9 in p.extensions

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_roman_numeral("")
        with pytest.raises(ValueError):
            parse_roman_numeral("XYZ")


# ---------------------------------------------------------------------------
# Chord building — these are the tests that catch musically-wrong output
# ---------------------------------------------------------------------------

class TestChordBuilding:
    def test_C_major_I_is_C_major_triad(self):
        p = parse_roman_numeral("I")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # C E G
        assert chord.pitch_classes == (0, 4, 7)
        assert chord.midi_notes == (60, 64, 67)

    def test_C_major_V_is_G_major_triad(self):
        p = parse_roman_numeral("V")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # G B D
        assert chord.pitch_classes == (7, 11, 2)
        # Voiced from G4 (MIDI 67)
        assert chord.midi_notes == (67, 71, 74)

    def test_C_major_vi_is_A_minor_triad(self):
        p = parse_roman_numeral("vi")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # A C E
        assert chord.pitch_classes == (9, 0, 4)

    def test_V7_in_C_is_G7(self):
        p = parse_roman_numeral("V7")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # G B D F
        assert chord.pitch_classes == (7, 11, 2, 5)

    def test_Imaj7_has_major_seventh(self):
        p = parse_roman_numeral("Imaj7")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # C E G B (major 7 = B, not Bb)
        assert chord.pitch_classes == (0, 4, 7, 11)

    def test_ii7_in_C_is_Dm7(self):
        p = parse_roman_numeral("ii7")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # D F A C
        assert chord.pitch_classes == (2, 5, 9, 0)

    def test_secondary_V_of_vi_in_C_is_E_major(self):
        """V/vi in C major should be E major (the V of A minor)."""
        p = parse_roman_numeral("V/vi")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # E G# B
        assert chord.pitch_classes == (4, 8, 11)

    def test_secondary_V7_of_ii_in_C_is_A7(self):
        """V7/ii in C major should be A7 (the V7 of D minor)."""
        p = parse_roman_numeral("V7/ii")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # A C# E G
        assert chord.pitch_classes == (9, 1, 4, 7)

    def test_bVII_in_C_major_is_Bb_major(self):
        """bVII in C major (modal mixture from mixolydian) is Bb major."""
        p = parse_roman_numeral("bVII")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # Bb D F
        assert chord.pitch_classes == (10, 2, 5)

    def test_bIII_in_C_major_is_Eb_major(self):
        """bIII in C major (modal mixture from minor) is Eb major."""
        p = parse_roman_numeral("bIII")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # Eb G Bb
        assert chord.pitch_classes == (3, 7, 10)

    def test_dorian_IV_is_major(self):
        """In D dorian, IV (G) is a major triad — the modal signature."""
        p = parse_roman_numeral("IV")
        chord = build_chord(p, key_pc=2, mode="dorian", octave=4)
        # G B D
        assert chord.pitch_classes == (7, 11, 2)

    def test_minor_key_iv_is_minor(self):
        """In A minor (aeolian), iv is D minor."""
        p = parse_roman_numeral("iv")
        chord = build_chord(p, key_pc=9, mode="minor", octave=4)
        # D F A
        assert chord.pitch_classes == (2, 5, 9)

    def test_V7b9_has_flat_nine(self):
        p = parse_roman_numeral("V7b9")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # G B D F Ab — the Ab is the b9
        assert 8 in chord.pitch_classes  # Ab

    def test_ii9_in_F_is_Gm9(self):
        """ii9 in F major: G Bb D F A"""
        p = parse_roman_numeral("ii9")
        chord = build_chord(p, key_pc=parse_pitch_class("F"), mode="major", octave=4)
        # G Bb D F A
        assert set(chord.pitch_classes) == {7, 10, 2, 5, 9}

    def test_inversion_first(self):
        """First inversion of C major should put E in the bass."""
        p = parse_roman_numeral("I6")
        chord = build_chord(p, key_pc=0, mode="major", octave=4)
        # Lowest note should now be E, not C.
        assert chord.midi_notes[0] % 12 == 4  # E
