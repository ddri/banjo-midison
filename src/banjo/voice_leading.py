"""
Voice leading for chord progressions.

Picks each chord's inversion + octave register to minimize voice motion
from the previous chord. See docs/superpowers/specs/2026-04-28-voice-leading-design.md
for the full algorithm and rationale.
"""

from __future__ import annotations


def _voicing_distance(candidate: list[int], previous: list[int]) -> int:
    """
    Sum of nearest-neighbor MIDI distances from each candidate note to
    the previous chord. Asymmetric: two candidate notes may share the same
    nearest neighbor. See spec section "Voicing distance" for why this is
    the chosen metric and what its limitations are.
    """
    return sum(min(abs(c - p) for p in previous) for c in candidate)
