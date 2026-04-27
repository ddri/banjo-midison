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

For the first chord: render exactly as today (use the request-level `octave`, the chord's `voicing`, and the chord's inversion). It is the seed.

For each subsequent chord, when `voice_lead` is true:

1. Determine the candidate inversion set:
   - If the user explicitly set an inversion on this chord (either via numeral shorthand like `V64` / `V42`, or via the `inversion` field), the set is `{that inversion}` — voice leading does not override user intent.
   - Otherwise, the set is `{0, 1, …, min(3, N−1)}` where `N` is the voiced note count. This caps inversion at the 3rd (the 7th in the bass); 9ths, 11ths, and 13ths participate in voice leading as upper voices but are never placed in the bass.
2. For each candidate inversion, build the chord at that inversion (via `build_chord`) and apply the user's voicing (via `apply_voicing`, unchanged).
3. For each voiced result, enumerate octave shifts `k ∈ {−2, −1, 0, +1, +2}`. The full candidate space is the cross-product (inversion × k) — up to 4 × 5 = 20 candidates per chord.
4. Score every candidate directly by **voicing distance** (defined below).
5. Pick the lowest-scoring candidate. Ties are broken by preferring (a) the smaller inversion number, (b) the smaller `|k|`, then (c) the smaller signed `k`. Deterministic.

When `voice_lead` is false, or when there is no previous chord (chord 1, or a single-chord progression): skip steps 1–5 entirely. Render exactly as today using the supplied octave, voicing, and inversion. The candidate-selection function is never invoked without a previous chord.

### Inversion / voicing order

Inversion is applied by `build_chord` *before* the voicing transformation in `apply_voicing`. For most voicings this is unambiguous (drop2 of inv-1 vs drop2 of inv-0 are different sounds — both legitimate candidates).

For `rootless` specifically, the lowest-note-dropped depends on which inversion was applied first:

- inv 0 + rootless → root dropped, 3rd in the bass
- inv 1 + rootless → 3rd dropped, 5th in the bass
- inv 2 + rootless → 5th dropped, 7th in the bass
- inv 3 + rootless → 7th dropped, root in the bass (rotated up an octave)

The candidate set is still `{0, …, min(3, N−1)}` where `N` is the post-voicing note count (so rootless of a 7th chord has 3 voices and a 3-element candidate set). "Inversion 0" of a rootless chord therefore does not mean "root in the bass" — it means "the original root-position chord, with its lowest note dropped." This is the existing pipeline; voice leading does not change it.

### Voicing distance

For a candidate chord and the previous chord's voiced notes, the score is: for each note `n` in the candidate, find the minimum absolute MIDI distance from `n` to any note in the previous chord, and sum those distances. Lower = closer.

This is **not** voice-identity tracking — two candidate notes may pick the same nearest neighbor in the previous chord, and there is no one-to-one voice mapping. It is an asymmetric register-similarity score that is cheap, deterministic, and sufficient for picking smooth-sounding inversions.

For the inversion-selection use case here, voice counts are constant within a single chord's candidate space (same chord and voicing, just different inversion + octave shift), so the asymmetry does not bias one candidate over another. The asymmetry would only matter when comparing across chords with different voice counts (e.g. close vs rootless), and the algorithm never does that — it only compares candidates of the *same* chord.

Determinism depends on `apply_voicing` being a pure function of `(notes, voicing)`. It is today (`voicings.py` sorts its input and holds no state); a regression test pins this.

### Octave handling

The request-level `octave` field seeds chord 1 only. From chord 2 onward, the per-chord octave shift `k` (chosen by step 3) determines register. `octave` therefore controls where the progression *starts*; the algorithm controls where each subsequent chord *sits relative to its predecessor*.

There is no per-chord octave override on `ChordSpec` today. If one is added later, the rule should be: an explicit per-chord octave pins `k = 0` for that chord, analogous to how an explicit inversion pins the candidate inversion set.

### Worked example

`I → V` in C major, both `close` voicing, `voice_lead: true`. Previous chord = [60, 64, 67] (C-E-G).

V candidate space (showing the best `k` per inversion):

| Inversion | k  | Notes        | Voicing distance |
|-----------|----|--------------|------------------|
| root      | −1 | [55, 59, 62] | 5 + 1 + 2 = 8    |
| 1st       | −1 | [59, 62, 67] | 1 + 2 + 0 = **3** |
| 2nd       |  0 | [62, 67, 71] | 2 + 0 + 4 = 6    |

Winner: 1st inversion of V at `k = −1`, giving B-D-G. Voices move 60→59 (−1), 64→62 (−2), 67→67 (0) — the G common tone is preserved and the other voices step.

Without voice leading the same input produces V at root position [67, 71, 74], with every voice jumping a 4th up.

## Code structure

**New file:** `src/banjo/voice_leading.py`

Single public function:

```python
def choose_voicing_position(
    candidates: list[list[int]],
    previous_notes: list[int],
) -> list[int]:
    """
    Pick the (inversion, octave-shift) combination that minimizes voicing
    distance from previous_notes.

    `candidates` is the list of per-inversion voiced note lists (caller has
    already applied build_chord + apply_voicing for each candidate inversion).
    The function expands the cross-product with k ∈ {-2, -1, 0, +1, +2}
    internally and returns the winning shifted notes.

    Precondition: `previous_notes` is non-empty. The function is not called
    for chord 1; that path renders directly with the request-level seed.
    """
```

Naming choice: `choose_voicing_position` rather than `choose_inversion` — the function picks both inversion and register, so the name should reflect both axes.

Plus one private helper for the voicing-distance score.

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

- `I → V` in C major, both close, voice_lead on → V comes out as 1st inversion at `k=−1` (the worked example above).
- `I → V` in C major, both close, voice_lead off → V comes out as root position (unchanged behavior).
- Explicit inversion respected: `V64` with voice_lead on stays second inversion *and* its `k` is the one minimizing voicing distance among the 5 candidates at that inversion. (Pinning inversion does not pin `k`; otherwise this case silently reverts to non-voice-led behavior.)
- Explicit inversion via `ChordSpec.inversion=1` respected the same way: inversion forced, `k` still chosen by score.
- Extension cap: a 13th chord (e.g. `V13`) with voice_lead on never lands with the 9th, 11th, or 13th in the bass — only the root, 3rd, 5th, or 7th can be the lowest note.
- Determinism: same input twice yields identical MIDI bytes.
- Tie-breaking: when two candidates score equally, the smaller inversion number wins; subsequent ties prefer smaller `|k|`, then smaller signed `k`.
- Voicing preservation: with `voice_lead` on and `voicing="drop2"`, every output chord still has drop2 spacing relationships (2nd-from-top is an octave below where it would be in close position).
- Rootless sanity: `I → ii` with chord 1 close (4 voices) and chord 2 rootless (3 voices) still produces a sensible inversion choice — voice leading only compares candidates of the *same* chord, so the cross-chord voice-count mismatch doesn't bias the score.
- Register stability under stress: a chromatic-mediant chain `I → bIII → bVI → III → I` in C major (large root motion, sympathetic to runaway drift) stays within ±12 semitones of the starting register, measured by the lowest note across all chords. This is an *empirical* test — the algorithm doesn't formally bound drift, but the score function (which inherently penalizes large `|k|` via larger voicing distances) plus the `|k|` tie-breaker produce stable behavior in practice. If a future change breaks that, this test will catch it.
- First chord is identical with and without voice_lead.
- `apply_voicing` purity regression: calling `apply_voicing` twice with the same `(notes, voicing)` returns identical lists (guards the determinism precondition).

Existing tests in `test_voicings.py`, `test_theory.py`, `test_midi_writer.py`, `test_mcp_server.py` should all continue to pass without modification.

## Migration / compatibility

`voice_lead` defaults to false. Every existing call site, test, and corpus file produces byte-identical output. The corpus (`corpus.py`) is not modified — those files remain the static audition fixtures they are today. We may later add a parallel `corpus_voice_led.py` to demonstrate the feature, but that is out of scope for this spec.
