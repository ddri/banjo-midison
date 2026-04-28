"""
Voice leading for chord progressions.

Picks each chord's inversion + octave register to minimize voice motion
from the previous chord. See docs/superpowers/specs/2026-04-28-voice-leading-design.md
for the full algorithm and rationale.
"""

from __future__ import annotations

import dataclasses

from banjo.theory import ParsedNumeral, build_chord
from banjo.voicings import VoicingName, apply_voicing


def _voicing_distance(candidate: list[int], previous: list[int]) -> int:
    """
    Sum of nearest-neighbor MIDI distances from each candidate note to
    the previous chord. Asymmetric: two candidate notes may share the same
    nearest neighbor. See spec section "Voicing distance" for why this is
    the chosen metric and what its limitations are.
    """
    return sum(min(abs(c - p) for p in previous) for c in candidate)


_K_RANGE = (-2, -1, 0, 1, 2)


def choose_voicing_position(
    candidates: list[list[int]],
    previous_notes: list[int],
) -> tuple[int, list[int]]:
    """
    Pick the (inversion, octave-shift) combination that minimizes voicing
    distance from previous_notes.

    `candidates` is a list of voiced note lists, one per candidate inversion
    (caller has already applied build_chord + apply_voicing for each).
    The function expands the cross-product with k in {-2, -1, 0, +1, +2}
    internally and returns (inv_idx, shifted_notes) for the winning candidate.

    Tie-break order: smaller inversion index, then smaller |k|, then
    smaller signed k.

    Precondition: previous_notes is non-empty. The function is not called
    for chord 1; that path renders directly with the request-level seed.
    """
    if not previous_notes:
        raise ValueError("previous_notes must be non-empty")
    if not candidates:
        raise ValueError("candidates must be non-empty")

    best_score: int | None = None
    best_notes: list[int] | None = None
    best_inv: int | None = None
    best_key: tuple[int, int, int] | None = None

    for inv_idx, voiced in enumerate(candidates):
        for k in _K_RANGE:
            shifted = [n + 12 * k for n in voiced]
            score = _voicing_distance(shifted, previous_notes)
            tie_key = (inv_idx, abs(k), k)
            if best_score is None or score < best_score or (
                score == best_score and tie_key < best_key
            ):
                best_score = score
                best_notes = shifted
                best_inv = inv_idx
                best_key = tie_key

    assert best_notes is not None and best_inv is not None
    return best_inv, best_notes


def build_candidates(
    parsed: ParsedNumeral,
    key_pc: int,
    mode: str,
    octave: int,
    voicing: VoicingName,
    explicit_inversion: bool,
) -> list[list[int]]:
    """
    Build the candidate set of voiced chord notes for voice leading.

    If explicit_inversion is True, the candidate set is {parsed.inversion}.
    Otherwise it is {0, 1, ..., min(3, N-1)} where N is the post-voicing
    note count (chord note count minus 1 if voicing is 'rootless', else
    unchanged).

    Each candidate is built via build_chord(modified_inversion) followed
    by apply_voicing(voicing). Returns a list of voiced note lists, one
    per candidate inversion.
    """
    if explicit_inversion:
        inversions = [parsed.inversion]
    else:
        # Build once at root position to count pre-voicing notes.
        chord_root = build_chord(
            dataclasses.replace(parsed, inversion=0), key_pc, mode, octave=octave,
        )
        n_pre = len(chord_root.midi_notes)
        n_post = n_pre - 1 if voicing == "rootless" else n_pre
        max_inv = min(3, n_post - 1)
        inversions = list(range(max_inv + 1))

    candidates: list[list[int]] = []
    for inv in inversions:
        chord = build_chord(
            dataclasses.replace(parsed, inversion=inv), key_pc, mode, octave=octave,
        )
        voiced = apply_voicing(list(chord.midi_notes), voicing)
        candidates.append(voiced)
    return candidates
