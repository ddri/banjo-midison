"""
Music theory primitives for banjo.

Conventions:
- Pitch class: integer 0-11, where 0 = C, 1 = C#/Db, ..., 11 = B.
- MIDI note number: integer 0-127, where 60 = middle C (C4).
- Scale degrees are 1-indexed (1 = tonic, 7 = leading tone).
- Roman numerals follow standard analysis: case denotes triad quality
  (uppercase = major/augmented, lowercase = minor/diminished); modifiers
  follow the numeral.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Pitch class primitives
# ---------------------------------------------------------------------------

PITCH_CLASS_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PITCH_CLASS_NAMES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

NOTE_TO_PITCH_CLASS = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4, "E#": 5, "F": 5, "F#": 6, "Gb": 6,
    "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10,
    "B": 11, "Cb": 11, "B#": 0,
}


def parse_pitch_class(name: str) -> int:
    """Parse a note name like 'C', 'F#', 'Bb' into a pitch class (0-11)."""
    if name not in NOTE_TO_PITCH_CLASS:
        raise ValueError(f"Unknown note name: {name!r}")
    return NOTE_TO_PITCH_CLASS[name]


def pitch_class_name(pc: int, prefer_flats: bool = False) -> str:
    """Render a pitch class (0-11) as a note name."""
    pc = pc % 12
    return PITCH_CLASS_NAMES_FLAT[pc] if prefer_flats else PITCH_CLASS_NAMES_SHARP[pc]


def midi_note_name(midi: int, prefer_flats: bool = False) -> str:
    """Render a MIDI note number as e.g. 'C4', 'F#3'."""
    pc = midi % 12
    octave = (midi // 12) - 1  # MIDI 60 = C4
    return f"{pitch_class_name(pc, prefer_flats)}{octave}"


# ---------------------------------------------------------------------------
# Scales / modes
# ---------------------------------------------------------------------------

# Intervals from tonic in semitones for each diatonic mode.
MODE_INTERVALS: dict[str, tuple[int, ...]] = {
    "major":      (0, 2, 4, 5, 7, 9, 11),   # Ionian
    "ionian":     (0, 2, 4, 5, 7, 9, 11),
    "dorian":     (0, 2, 3, 5, 7, 9, 10),
    "phrygian":   (0, 1, 3, 5, 7, 8, 10),
    "lydian":     (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "minor":      (0, 2, 3, 5, 7, 8, 10),   # Aeolian (natural minor)
    "aeolian":    (0, 2, 3, 5, 7, 8, 10),
    "locrian":    (0, 1, 3, 5, 6, 8, 10),
}

# Default triad quality on each scale degree per mode.
# 'M' = major, 'm' = minor, 'd' = diminished, 'A' = augmented.
MODE_TRIAD_QUALITIES: dict[str, tuple[str, ...]] = {
    "major":      ("M", "m", "m", "M", "M", "m", "d"),
    "ionian":     ("M", "m", "m", "M", "M", "m", "d"),
    "dorian":     ("m", "m", "M", "M", "m", "d", "M"),
    "phrygian":   ("m", "M", "M", "m", "d", "M", "m"),
    "lydian":     ("M", "M", "m", "d", "M", "m", "m"),
    "mixolydian": ("M", "m", "d", "M", "m", "m", "M"),
    "minor":      ("m", "d", "M", "m", "m", "M", "M"),
    "aeolian":    ("m", "d", "M", "m", "m", "M", "M"),
    "locrian":    ("d", "M", "m", "m", "M", "M", "m"),
}


def scale_pitch_classes(tonic_pc: int, mode: str) -> tuple[int, ...]:
    """Return the seven pitch classes of a scale, starting on the tonic."""
    if mode not in MODE_INTERVALS:
        raise ValueError(f"Unknown mode: {mode!r}")
    return tuple((tonic_pc + iv) % 12 for iv in MODE_INTERVALS[mode])


# ---------------------------------------------------------------------------
# Roman numeral parsing
# ---------------------------------------------------------------------------

ROMAN_TO_DEGREE = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}

# Quality inferred from the case + symbol on the numeral itself.
# Symbols: 'o' or '°' = diminished, '+' = augmented, otherwise case decides.
QUALITY_DIMINISHED = "d"
QUALITY_AUGMENTED = "A"
QUALITY_MAJOR = "M"
QUALITY_MINOR = "m"

# Recognised seventh / extension shorthands. Order matters: longer keys first.
EXTENSION_TOKENS = ("maj13", "maj11", "maj9", "maj7", "13", "11", "9", "7")

# Recognised alteration tokens.
ALTERATION_PATTERN = re.compile(r"([b#])(5|9|11|13)")


@dataclass
class ParsedNumeral:
    """A parsed Roman numeral, fully resolved against a key + mode."""
    raw: str
    degree: int                      # 1..7 within the (possibly secondary) key
    quality: str                     # 'M' | 'm' | 'd' | 'A'
    extensions: tuple[int, ...]      # e.g. (7,) or (7, 9, 13). Always sorted.
    alterations: tuple[str, ...]     # e.g. ('b9', '#11')
    inversion: int                   # 0..3, derived from slash or explicit
    accidental: int                  # semitone offset on the root: -1 (b), 0, +1 (#)
    secondary_of: int | None = None  # if 'V/vi', this is 6 (the target degree)
    bass_degree: int | None = None   # for slash chords like 'I/3' or 'V/B'


def parse_roman_numeral(raw: str) -> ParsedNumeral:
    """
    Parse a Roman numeral string into structured form.

    Supported syntax (examples):
        I, ii, iii, IV, V, vi, vii°, vii, III+
        Imaj7, ii7, V7, V13, vi9, ivm9 (lowercase 'm' is redundant but accepted)
        V7b9, V7#11, ii7b5
        bVII, bIII, #IV (modal mixture / chromatic roots)
        V/vi, V7/ii, viio7/V (secondary function)
        V6, V64, I6 (figured-bass inversion shorthand: 6 = first, 64 = second, 65/43/42 = seventh inversions)

    The grammar is intentionally permissive but strict about ambiguity.
    """
    s = raw.strip()
    if not s:
        raise ValueError("Empty numeral")

    # 1. Split off secondary function (everything after the LAST '/' that
    #    isn't part of figured-bass shorthand).
    secondary_of: int | None = None
    if "/" in s:
        head, tail = s.rsplit("/", 1)
        # Distinguish 'V/vi' (secondary) from 'I/3' (bass-note slash) from
        # figured-bass like 'V64' (no slash anyway). If the tail looks like a
        # numeral, treat as secondary; otherwise treat as bass-note slash.
        if _looks_like_numeral(tail):
            secondary_of = _numeral_to_degree(tail)
            s = head
        # bass-note slashes (I/3, V/B) handled later as bass_degree

    # 2. Leading accidental on the root (b, #).
    accidental = 0
    if s.startswith("b"):
        accidental = -1
        s = s[1:]
    elif s.startswith("#"):
        accidental = 1
        s = s[1:]

    # 3. The numeral itself: longest match from {VII, VI, IV, V, III, II, I},
    #    case-sensitive.
    numeral_match = re.match(r"(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)", s)
    if not numeral_match:
        raise ValueError(f"Could not find Roman numeral in {raw!r}")
    numeral = numeral_match.group(1)
    s = s[numeral_match.end():]
    degree = ROMAN_TO_DEGREE[numeral.upper()]
    is_uppercase = numeral.isupper()

    # 4. Quality marker immediately after numeral: o, °, +, or lowercase 'm'.
    quality_override: str | None = None
    if s.startswith(("o", "°")):
        quality_override = QUALITY_DIMINISHED
        s = s[1:]
    elif s.startswith("ø"):
        # Half-diminished. Treated as diminished triad with a minor 7 added.
        # We mark quality as 'd' and force a m7 extension below.
        quality_override = QUALITY_DIMINISHED
        s = s[1:]
        # Inject '7' so the seventh gets added.
        s = "7" + s
    elif s.startswith("+"):
        quality_override = QUALITY_AUGMENTED
        s = s[1:]
    elif s.startswith("m") and not s.startswith("maj"):
        # Lowercase 'm' on a minor numeral is redundant; on an uppercase
        # numeral (e.g. 'IVm') it forces minor.
        quality_override = QUALITY_MINOR
        s = s[1:]

    if quality_override is not None:
        quality = quality_override
    else:
        quality = QUALITY_MAJOR if is_uppercase else QUALITY_MINOR

    # 5. Extensions (maj7, 7, 9, 11, 13, etc).
    extensions: list[int] = []
    while True:
        matched = False
        for tok in EXTENSION_TOKENS:
            if s.startswith(tok):
                if tok.startswith("maj"):
                    # maj7 forces a major 7th regardless of triad quality.
                    n = int(tok[3:])
                    extensions.append(n)
                    # Imply lower extensions: 9 implies 7, 11 implies 7+9, etc.
                    for implied in (7, 9, 11):
                        if implied < n and implied not in extensions:
                            extensions.append(implied)
                    # Mark as major-7 explicitly via a sentinel alteration.
                    s = s[len(tok):]
                    matched = True
                    # Track that the 7 should be major (handled in builder).
                    extensions.append(-7)  # sentinel: maj7
                    break
                else:
                    n = int(tok)
                    extensions.append(n)
                    for implied in (7, 9, 11):
                        if implied < n and implied not in extensions:
                            extensions.append(implied)
                    s = s[len(tok):]
                    matched = True
                    break
        if not matched:
            break

    # 6. Alterations (b5, #5, b9, #9, #11, b13).
    alterations: list[str] = []
    for m in ALTERATION_PATTERN.finditer(s):
        alterations.append(f"{m.group(1)}{m.group(2)}")
    s = ALTERATION_PATTERN.sub("", s)

    # 7. Figured-bass inversion shorthand or explicit bass-note slash.
    inversion = 0
    bass_degree: int | None = None
    s = s.strip()
    if s in ("6", "63"):
        inversion = 1
    elif s in ("64",):
        inversion = 2
    elif s in ("7", "65"):
        # '7' alone was already consumed as an extension above; '65' here
        # means first inversion of a seventh chord.
        if s == "65":
            inversion = 1
    elif s == "43":
        inversion = 2
    elif s == "42" or s == "2":
        inversion = 3
    elif s:
        # Unparsed remainder — could be a bass-note slash (handled earlier)
        # or genuinely unknown. We tolerate empty; otherwise raise.
        raise ValueError(f"Unparsed remainder {s!r} in numeral {raw!r}")

    # Dedupe + sort extensions, keeping the maj7 sentinel if present.
    has_maj7 = -7 in extensions
    ext_clean = sorted({e for e in extensions if e > 0})
    if has_maj7:
        ext_clean = [-7] + ext_clean

    return ParsedNumeral(
        raw=raw,
        degree=degree,
        quality=quality,
        extensions=tuple(ext_clean),
        alterations=tuple(alterations),
        inversion=inversion,
        accidental=accidental,
        secondary_of=secondary_of,
        bass_degree=bass_degree,
    )


def _looks_like_numeral(s: str) -> bool:
    """Heuristic: does this token look like a Roman numeral?"""
    s = s.lstrip("b#")
    return bool(re.match(r"^(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)", s))


def _numeral_to_degree(s: str) -> int:
    """Extract just the scale degree from a numeral token."""
    s = s.lstrip("b#")
    m = re.match(r"(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)", s)
    if not m:
        raise ValueError(f"Not a numeral: {s!r}")
    return ROMAN_TO_DEGREE[m.group(1).upper()]


# ---------------------------------------------------------------------------
# Chord building
# ---------------------------------------------------------------------------

@dataclass
class ResolvedChord:
    """A fully resolved chord: pitch classes and a suggested register."""
    numeral: str
    root_pc: int
    quality: str
    pitch_classes: tuple[int, ...]   # in chord-tone order: root, 3rd, 5th, ...
    midi_notes: tuple[int, ...]      # voiced in a specific octave
    inversion: int = 0


# Triad interval signatures from the root, in semitones.
TRIAD_INTERVALS = {
    QUALITY_MAJOR:      (0, 4, 7),
    QUALITY_MINOR:      (0, 3, 7),
    QUALITY_DIMINISHED: (0, 3, 6),
    QUALITY_AUGMENTED:  (0, 4, 8),
}


def build_chord(
    parsed: ParsedNumeral,
    key_pc: int,
    mode: str,
    octave: int = 4,
) -> ResolvedChord:
    """
    Build a chord's pitch classes and a default close-position voicing.

    The voicing returned here is the raw 'stack of thirds' starting at the
    given octave, with inversion applied. Voicing transformations
    (drop2, rootless, etc.) are applied in voicings.py.
    """
    # Resolve the root pitch class. For a secondary function 'V/vi', the
    # 'vi' establishes a temporary tonic, and the 'V' is built off that
    # temporary tonic's dominant.
    if parsed.secondary_of is not None:
        target_scale = scale_pitch_classes(key_pc, mode)
        temp_tonic_pc = target_scale[parsed.secondary_of - 1]
        # Secondary chords are conventionally built from the major scale of
        # the temporary tonic.
        root_pc = scale_pitch_classes(temp_tonic_pc, "major")[parsed.degree - 1]
    else:
        scale = scale_pitch_classes(key_pc, mode)
        root_pc = scale[parsed.degree - 1]

    root_pc = (root_pc + parsed.accidental) % 12

    # Build the triad.
    intervals = list(TRIAD_INTERVALS[parsed.quality])

    # Add seventh / extensions.
    has_maj7 = -7 in parsed.extensions
    numeric_exts = [e for e in parsed.extensions if e > 0]

    if 7 in numeric_exts:
        # Default seventh: minor 7 for dominant/minor/half-dim, major 7 only
        # if explicitly maj7 or if the triad quality is major and the
        # numeral didn't specify plain '7'.
        if has_maj7:
            intervals.append(11)
        elif parsed.quality == QUALITY_DIMINISHED and not has_maj7:
            # Half-diminished (m7) vs fully-diminished (bb7). We default to
            # half-diminished here; the 'ø' shorthand has already injected '7'.
            intervals.append(10)
        else:
            intervals.append(10)

    if 9 in numeric_exts:
        intervals.append(14)
    if 11 in numeric_exts:
        intervals.append(17)
    if 13 in numeric_exts:
        intervals.append(21)

    # Apply alterations.
    for alt in parsed.alterations:
        sign, deg = alt[0], int(alt[1:])
        delta = -1 if sign == "b" else 1
        target_interval = {5: 7, 9: 14, 11: 17, 13: 21}[deg]
        if target_interval in intervals:
            idx = intervals.index(target_interval)
            intervals[idx] = target_interval + delta
        else:
            intervals.append(target_interval + delta)

    intervals = sorted(set(intervals))

    # Voice in the requested octave: root at C{octave} reference,
    # i.e. root MIDI = (octave + 1) * 12 + root_pc.
    root_midi = (octave + 1) * 12 + root_pc
    midi_notes = tuple(root_midi + iv for iv in intervals)

    # Apply inversion by rotating the lowest note(s) up an octave.
    if parsed.inversion > 0:
        notes = list(midi_notes)
        for _ in range(min(parsed.inversion, len(notes) - 1)):
            notes[0] += 12
            notes.sort()
        midi_notes = tuple(notes)

    pitch_classes = tuple((root_pc + iv) % 12 for iv in intervals)

    return ResolvedChord(
        numeral=parsed.raw,
        root_pc=root_pc,
        quality=parsed.quality,
        pitch_classes=pitch_classes,
        midi_notes=midi_notes,
        inversion=parsed.inversion,
    )
