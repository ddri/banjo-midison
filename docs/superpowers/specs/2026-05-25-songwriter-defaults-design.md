# Songwriter Defaults — Design Spec

**Date:** 2026-05-25
**Status:** Approved

## Problem

The MCP tool produces rootless, register-floating jazz voicings even when the user asks for genre/mood references like "Morcheeba" or "Thievery Corporation". The tool schema and description use jazz pedagogy language ("rootless — bassist plays the root", "jazz piano staple") which primes Claude to treat every generation as a jazz ensemble arrangement rather than a self-contained DAW clip for a solo producer.

Two concrete failure modes:
1. **Rootless voicings** — root note omitted from MIDI; sounds bassless and thin loaded alone into Ableton
2. **High register** — chords placed in octave 5–6+, floating above where most DAW arrangements live

## Design

### 1. Extract rootless as an explicit opt-in flag

Remove `rootless` from the `voicing` enum. Add it as a separate per-chord boolean field.

**Before:** `voicing: enum[close, drop2, drop3, drop2and4, spread, rootless]`

**After:**
```
voicing: enum[close, drop2, drop3, drop2and4, spread]   # default: close
rootless: bool                                           # default: false
```

The `rootless` field description: *"Omit the root note from the chord. Only use this when a separate bass instrument is playing the root — not appropriate for solo piano or standalone DAW clips."*

The underlying `_rootless()` function in `voicings.py` is unchanged. The rootless step is applied in `midi_writer.py` as part of the chord resolution pipeline (see Order of Operations below).

#### spread + rootless interaction

`voicing: spread` with `rootless: true` is a validation error. Spread is defined as "root dropped an octave below the upper structure" — removing the root after spread produces a result with no useful interpretation (effectively close position, minus one note). Raise a `ValueError` in `_build_generation_request` with the message: *"rootless: true cannot be combined with voicing: spread — spread is defined by its bass root."*

#### Migration error for stale callers

A caller passing `voicing: "rootless"` (old API) will now hit a generic enum validation error. Add an explicit pre-check in `_build_generation_request` that detects this and raises: *"'rootless' is no longer a voicing option — pass rootless: true alongside your chosen voicing (e.g. voicing: 'close', rootless: true)."*

### 2. Lower the default octave; add max_octave clamp

- Change `octave` default from `4` to `3`
- Add `max_octave` field, default `5`, minimum `0`, maximum `9`

`octave` field description: *"Root octave. Follows Ableton convention: C3 = MIDI 60 (middle C). Default 3 puts chords in a comfortable mid-low piano register. For most songwriting, stay between 2 and 4. Above 5 puts chords in melody territory."*

`max_octave` field description: *"Hard ceiling on chord register (Ableton convention). Any chord that resolves above this octave is shifted down by whole octaves until it is at or below max_octave. Applied after voice leading. Default 5 prevents runaway high voicings."*

#### max_octave clamp semantics

- Detect the octave of the chord's lowest note after all other processing.
- Shift the entire chord down by whole octaves (subtract 12 per octave) until the lowest note is at or below `max_octave`.
- A chord already at or below `max_octave` passes through unchanged.
- Applied **after** `voice_lead` (see Order of Operations). This means voice leading may be partially undone by a clamp — that is acceptable; `max_octave` is a hard safety constraint, not a soft preference.

### 3. Order of operations

For each chord in the pipeline, the resolution order is:

```
1. build_chord()          — theory engine produces close-position notes
2. apply_voicing()        — drop2, drop3, spread, etc.
3. voice_lead()           — (if voice_lead: true) adjust inversion/register to minimise motion
4. apply rootless         — (if rootless: true) strip root note
5. apply max_octave clamp — shift down until lowest note ≤ max_octave
```

This order is documented inline in `midi_writer.py` at the chord resolution call site.

**Rationale:** voice_lead sees the complete chord (including root) so it can compute correct transitions. Rootless strips the root after voice leading — the transition was already optimised. max_octave is the final safety net; it runs last so it catches anything the voice leader pushed too high.

### 4. Rewrite tool and field descriptions

**Tool description:** Opens with *"Generate a MIDI chord progression for a solo producer or songwriter to load into a DAW. Chords are self-contained — the root is always included unless rootless is explicitly set."* Remove all references to bassists, jazz ensembles, and jazz piano pedagogy.

**Voicing field descriptions:** Replace jazz framing with sound descriptions:
- `close` — *"Stacked thirds, compact and clear."*
- `drop2` — *"Second-from-top voice dropped an octave. Opens up the voicing, slightly warmer."*
- `drop3` — *"Third-from-top voice dropped an octave. Fuller spread across the register."*
- `drop2and4` — *"Second and fourth from top dropped an octave. Wide, open voicing."*
- `spread` — *"Root dropped an octave below the upper structure. Wide gap between bass and upper voices."*

## Files Changed

| File | Change |
|------|--------|
| `src/banjo/mcp_server.py` | Remove rootless from voicing enum; add rootless bool per chord; add max_octave field; change octave default to 3; rewrite descriptions; add spread+rootless validation; add migration error |
| `src/banjo/midi_writer.py` | Add max_octave clamping; handle rootless as post-voice_lead step; update ChordSpec and GenerationRequest dataclasses; document order of operations inline |
| `src/banjo/voicings.py` | No changes |

## What Does Not Change

- All existing voicing logic
- The `voice_lead` flag behaviour
- The Roman numeral parser and theory engine

## Testing

**Rootless:**
- `rootless: false` (default) — root note present in all voicings
- `rootless: true` with `close`, `drop2`, `drop3`, `drop2and4` — root stripped, remaining notes correct
- `rootless: true` with `spread` — raises `ValueError`
- Old `voicing: "rootless"` — raises targeted migration error

**max_octave:**
- Chord at exactly `max_octave` — passes through unchanged
- Chord one octave above `max_octave` — shifted down one octave
- Chord several octaves above `max_octave` — shifted down by N octaves to land at `max_octave`
- Chord with `voice_lead: true` that pushes above `max_octave` — clamped after voice leading

**Defaults:**
- Default octave is 3
- Default max_octave is 5
- Default rootless is false

**All 107 existing tests must continue passing.**
