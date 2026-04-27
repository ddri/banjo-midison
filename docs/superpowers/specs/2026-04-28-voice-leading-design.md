# Voice Leading — Design

**Date:** 2026-04-28
**Status:** Approved (awaiting implementation plan)

## Problem

Each chord in a Banjo progression is currently voiced independently. `apply_voicing` in `src/banjo/voicings.py` transforms a single chord; nothing connects consecutive chords. The audible result is that progressions sound *spelled* rather than *played* — voices teleport between chords instead of moving smoothly. A `I → V` in close position, for instance, jumps every voice by a 4th when proper voice leading would keep G as a common tone and move the others by step.

This spec adds optional voice leading: an opt-in mode that picks each chord's inversion to minimize voice motion from the previous chord, while preserving every other knob the user already controls.

## Goals

- Smooth voice motion between consecutive chords when the user opts in.
- Zero behavior change when the user does not opt in.
- Preserve the meaning of every existing voicing (`close`, `drop2`, `drop3`, `drop2and4`, `spread`, `rootless`).
- Respect explicitly-set inversions — `V64` or `inversion: 2` is a user instruction, not a suggestion.
- Deterministic output for a given input (no RNG, no ties broken randomly).

## Non-Goals

- SATB-style four-part voice leading with independent voice ranges.
- Classical voice-leading rules (no parallel fifths/octaves, leading-tone resolution, 7th resolution). These can come later as a separate `strict_voice_leading` flag if desired.
- Quartal, shell, upper-structure, or cluster voicings. Out of scope; those are *new voicings*, not voice leading.
- Voice leading across non-adjacent chords (e.g. global optimization). Each chord is voice-led only against its immediate predecessor.

## API

One new top-level field on the `generate_midi_progression` MCP tool and on `GenerationRequest`:

```
voice_lead: bool   (default false)
```

No changes to per-chord `ChordSpec` fields. No new voicing names. No new endpoints.

## Algorithm

For the first chord: render exactly as today (use the supplied octave, voicing, and inversion). It is the seed.

For each subsequent chord, when `voice_lead` is true:

1. Determine the candidate inversion set:
   - If the user explicitly set an inversion on this chord (either via numeral shorthand like `V64` / `V42`, or via the `inversion` field), the candidate set is `{that inversion}` — voice leading does not override user intent.
   - Otherwise, the candidate set is `{0, 1, 2}` for triads and `{0, 1, 2, 3}` for chords with a 7th.
2. For each candidate inversion:
   a. Build the chord at that inversion using the existing `build_chord` path.
   b. Apply the user's chosen voicing via `apply_voicing` (unchanged).
   c. Octave-shift the *whole* resulting chord by an integer number of octaves `k ∈ [-2, +2]` so that its mean pitch is closest to the previous chord's mean pitch. If two values of `k` tie, prefer the smaller `|k|`. (This stops voice leading from drifting the register over many chords.)
   d. Score the result: sum over voices of the minimum semitone distance from each note in this chord to any note in the previous chord. Lower score = smoother.
3. Pick the candidate with the lowest score. Ties are broken by preferring (a) the smaller inversion number, then (b) the smaller absolute octave shift `k`. Deterministic.

When `voice_lead` is false: skip steps 1–3 entirely. Render exactly as today.

### Scoring detail

"Voice motion" is computed as: for each note `n` in the candidate chord, find the closest note in the previous chord (by absolute MIDI distance), and sum those distances. This is asymmetric and tolerant of voice count changes (e.g. rootless chords have one fewer note). Simpler than maintaining explicit voice identity, and good enough for the smoothness signal we want.

### Worked example

`I → V` in C major, both `close` voicing, `voice_lead: true`:

- Chord 1 (I, root): [60, 64, 67] (C-E-G).
- Chord 2 (V) candidates:
  - root: G-B-D close = [67, 71, 74]. Score: |67-67|+|71-67|+|74-67| = 0+4+7 = 11.
  - 1st inv: B-D-G close = [71, 74, 79]. Score: 4+7+12 = 23.
  - 2nd inv: D-G-B close = [62, 67, 71]. Score: 2+0+4 = 6.
- Winner: 2nd inversion. Result: C-E-G → D-G-B. Voices move by 2, 3, 4 semitones — the common tone (G) is preserved, the other voices step.

Without voice leading the same input produces C-E-G → G-B-D, with every voice jumping a 4th.

## Code structure

**New file:** `src/banjo/voice_leading.py`

Single public function:

```python
def choose_inversion(
    candidates: list[ResolvedChord],
    previous_notes: list[int],
) -> ResolvedChord:
    """Pick the candidate whose voiced notes minimize voice motion from previous_notes."""
```

Plus one private helper for the octave-shift step.

**Modified files:**

- `src/banjo/midi_writer.py`: in the existing chord-building loop in `generate()`, when `request.voice_lead` is true and a previous chord exists, build all candidate inversions, apply the chord's voicing to each, call `choose_inversion`, and use the result. When false, behavior is byte-identical to today.
- `src/banjo/midi_writer.py`: add `voice_lead: bool = False` to `GenerationRequest`.
- `src/banjo/mcp_server.py`: add `voice_lead` boolean to `GENERATE_MIDI_PROGRESSION_SCHEMA`. Plumb it through `_build_generation_request`.

**Unchanged:** `theory.py`, `voicings.py`, `config.py`, `corpus.py`, MCP dispatcher.

## Determining "user explicitly set an inversion"

Two sources:

1. The parsed numeral has a non-zero `inversion` (because the user wrote `V64`, `V42`, etc.).
2. The `ChordSpec.inversion` field is not `None`.

If either is true, voice leading uses that inversion as the only candidate. If both are false, voice leading is free to pick.

## Testing

New file: `tests/test_voice_leading.py`. Cases:

- `I → V` in C major, both close, voice_lead on → V comes out as 2nd inversion (the worked example above).
- `I → V` in C major, both close, voice_lead off → V comes out as root position (unchanged behavior).
- Explicit inversion respected: `V64` with voice_lead on stays second inversion even if root would score lower.
- Explicit inversion via `ChordSpec.inversion=1` respected the same way.
- Determinism: same input twice yields identical MIDI bytes.
- Tie-breaking: when two candidates score equally, the smaller inversion number wins.
- Voicing preservation: with `voice_lead` on and `voicing="drop2"`, every output chord still has drop2 spacing relationships (2nd-from-top is an octave below where it would be in close position).
- Register stability: a long progression doesn't drift more than ~1 octave from the starting register.
- First chord is identical with and without voice_lead.

Existing tests in `test_voicings.py`, `test_theory.py`, `test_midi_writer.py`, `test_mcp_server.py` should all continue to pass without modification.

## Migration / compatibility

`voice_lead` defaults to false. Every existing call site, test, and corpus file produces byte-identical output. The corpus (`corpus.py`) is not modified — those files remain the static audition fixtures they are today. We may later add a parallel `corpus_voice_led.py` to demonstrate the feature, but that is out of scope for this spec.
