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

The underlying `_rootless()` function in `voicings.py` is unchanged. `_build_generation_request` applies it as a post-voicing step when `rootless: true`.

### 2. Lower the default octave; add max_octave clamp

- Change `octave` default from `4` to `3`
- Add `max_octave` field, default `5`, minimum `0`, maximum `9`
- `midi_writer.py` clamps each chord's resolved octave to `max_octave` at generation time

`octave` field description: *"Root octave. Default 3 puts chords in a comfortable mid-low piano register. For most songwriting, stay between 2 and 4. Above 5 puts chords in melody territory."*

`max_octave` field description: *"Hard ceiling on chord register. Chords that would resolve above this octave are shifted down. Default 5 prevents runaway high voicings."*

### 3. Rewrite tool and field descriptions

**Tool description:** Opens with *"Generate a MIDI chord progression for a solo producer or songwriter to load into a DAW. Chords are self-contained — the root is always included unless rootless is explicitly set."* Remove all references to bassists, jazz ensembles, and jazz piano pedagogy.

**Voicing field descriptions:** Replace jazz framing with sound descriptions:
- `close` — *"Stacked thirds, compact and clear."*
- `drop2` — *"Second-from-top voice dropped an octave. Opens up the voicing, slightly warmer."*
- `drop3` — *"Third-from-top voice dropped an octave. Fuller spread across the register."*
- `drop2and4` — *"Second and fourth from top dropped an octave. Wide, open voicing."*
- `spread` — *"Root dropped an octave below the upper structure. Good for piano-style LH/RH separation."*

## Files Changed

| File | Change |
|------|--------|
| `src/banjo/mcp_server.py` | Remove rootless from voicing enum; add rootless bool; add max_octave field; change octave default to 3; rewrite descriptions |
| `src/banjo/midi_writer.py` | Add max_octave clamping; handle rootless as post-voicing step; update ChordSpec and GenerationRequest dataclasses |
| `src/banjo/voicings.py` | No changes |

## What Does Not Change

- All existing voicing logic
- The `voice_lead` flag behaviour
- The Roman numeral parser and theory engine
- Existing callers passing `voicing: "rootless"` will break (intentional — rootless is now a separate field). No external users exist yet.

## Testing

- Existing tests for rootless voicing updated to use the new `rootless: true` flag
- New tests: `max_octave` clamps chords correctly; `rootless` defaults to false; default octave is 3
- All 107 existing tests must continue passing
