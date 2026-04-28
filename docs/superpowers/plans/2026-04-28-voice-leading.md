# Voice Leading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `voice_lead: bool` flag to Banjo's MIDI generator that picks each chord's inversion and octave register to minimize voice motion from the previous chord, while preserving every existing voicing and respecting explicit user-set inversions.

**Architecture:** New leaf-node module `src/banjo/voice_leading.py` exposing one public function `choose_voicing_position(candidates, previous_notes) → list[int]` and a candidate-building helper `build_candidates(...)`. `midi_writer.generate()`'s existing chord loop calls these only when `voice_lead=True`; the `voice_lead=False` path is byte-identical to today.

**Tech Stack:** Python 3 (existing), `mido` (existing), `mcp` SDK (existing), `pytest` (existing). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-28-voice-leading-design.md`

---

## File Structure

**New files:**
- `src/banjo/voice_leading.py` — `_voicing_distance`, `choose_voicing_position`, `build_candidates`
- `tests/test_voice_leading.py` — unit tests for the above

**Modified files:**
- `src/banjo/midi_writer.py` — add `voice_lead: bool = False` to `GenerationRequest`; integrate voice-leading branch in `generate()`'s chord loop
- `src/banjo/mcp_server.py` — add `voice_lead` to `GENERATE_MIDI_PROGRESSION_SCHEMA`; plumb through `_build_generation_request`
- `tests/test_voicings.py` — add `apply_voicing` purity regression
- `tests/test_midi_writer.py` — integration tests for the voice-led path
- `tests/test_mcp_server.py` — schema and plumbing tests

**Unchanged:** `theory.py`, `voicings.py`, `config.py`, `corpus.py`.

## Performance note

The cross-product is up to 4 inversions × 5 octave shifts = 20 candidates per chord, with up to ~6×6 = 36 distance comparisons per candidate (≤720 ops/chord). Negligible for any progression a human would write; if a profiler ever points here under a 1000-chord stress test, the fix is to memoize `_voicing_distance` per `(candidate_tuple, previous_tuple)`. Not needed today.

---

## Task 1: Voicing-distance score

**Files:**
- Create: `src/banjo/voice_leading.py`
- Create: `tests/test_voice_leading.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_voice_leading.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_voice_leading.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'banjo.voice_leading'`

- [ ] **Step 3: Write minimal implementation**

Create `src/banjo/voice_leading.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_voice_leading.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/banjo/voice_leading.py tests/test_voice_leading.py
git commit -m "Add voicing-distance score for voice leading

Nearest-neighbor MIDI distance, asymmetric. Sufficient for picking
smooth inversions of the same chord; documented as not voice-identity
tracking."
```

---

## Task 2: choose_voicing_position — picks inversion and octave shift

**Files:**
- Modify: `src/banjo/voice_leading.py`
- Modify: `tests/test_voice_leading.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_voice_leading.py`:

```python
from banjo.voice_leading import choose_voicing_position


class TestChooseVoicingPosition:
    def test_picks_optimal_k_for_single_inversion(self):
        # Previous: I close [60, 64, 67]
        # Candidate: V root close [67, 71, 74]
        # k=0: 0+4+7 = 11; k=-1: [55,59,62] -> 5+1+2 = 8
        # k=-1 wins
        result = choose_voicing_position([[67, 71, 74]], [60, 64, 67])
        assert sorted(result) == [55, 59, 62]

    def test_picks_lowest_scoring_inversion_worked_example(self):
        # Worked example from spec: I -> V in C, all close
        # root: [67,71,74] -> best k=-1 -> [55,59,62] score 8
        # 1st inv: [71,74,79] -> best k=-1 -> [59,62,67] score 3 <- winner
        # 2nd inv: [62,67,71] -> best k=0 score 6
        candidates = [[67, 71, 74], [71, 74, 79], [62, 67, 71]]
        result = choose_voicing_position(candidates, [60, 64, 67])
        assert sorted(result) == [59, 62, 67]

    def test_tie_break_prefers_smaller_abs_k(self):
        # previous=[60, 72], candidate=[[66]]
        # k=0: [66] -> min(6,6) = 6
        # k=-1: [54] -> min(6,18) = 6
        # k=+1: [78] -> min(18,6) = 6
        # All k tie. Smaller |k| wins -> k=0 -> [66]
        result = choose_voicing_position([[66]], [60, 72])
        assert result == [66]

    def test_tie_break_prefers_smaller_inversion_index(self):
        # Two inversions producing identical voiced notes -> idx 0 wins.
        # Both candidates are [60,64,67] vs previous [60,64,67] -> score 0 at k=0.
        # The function returns the inversion-0 candidate (which is idx 0).
        result = choose_voicing_position([[60, 64, 67], [60, 64, 67]], [60, 64, 67])
        assert sorted(result) == [60, 64, 67]

    def test_tie_break_signed_k_when_abs_k_ties(self):
        # previous=[60, 72]; candidate=[[60, 72]]
        # k=0: score 0. k=-1: [48,60] -> 12+0=12. k=+1: [72,84] -> 0+12=12.
        # k=0 wins by score. Build a case where k=-1 and k=+1 tie at the same score
        # AND that score beats k=0:
        # previous=[60]; candidate=[[72]]
        # k=0: 12. k=-1: [60] -> 0. k=+1: [84] -> 24. k=-1 wins by score (no tie).
        # Easier: just trust k=-1 over k=+1 via the tie-break rule on a constructed tie.
        # Use previous=[60, 84]; candidate=[[72]]:
        # k=0: [72] -> min(12, 12) = 12
        # k=-1: [60] -> min(0, 24) = 0  <- best
        # k=+1: [84] -> min(24, 0) = 0  <- ties best
        # Tie at 0. |k|=1 for both. Signed k smaller -> k=-1 -> [60].
        result = choose_voicing_position([[72]], [60, 84])
        assert result == [60]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_voice_leading.py::TestChooseVoicingPosition -v`
Expected: FAIL — `ImportError: cannot import name 'choose_voicing_position'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/banjo/voice_leading.py`:

```python
_K_RANGE = (-2, -1, 0, 1, 2)


def choose_voicing_position(
    candidates: list[list[int]],
    previous_notes: list[int],
) -> list[int]:
    """
    Pick the (inversion, octave-shift) combination that minimizes voicing
    distance from previous_notes.

    `candidates` is a list of voiced note lists, one per candidate inversion
    (caller has already applied build_chord + apply_voicing for each).
    The function expands the cross-product with k in {-2, -1, 0, +1, +2}
    internally and returns the winning shifted notes.

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
                best_key = tie_key

    assert best_notes is not None
    return best_notes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_voice_leading.py -v`
Expected: PASS — 9 passed (4 from Task 1 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add src/banjo/voice_leading.py tests/test_voice_leading.py
git commit -m "Add choose_voicing_position with deterministic tie-breaking

Picks (inversion, octave shift) jointly by score. Tie-break: smaller
inversion index, then smaller |k|, then smaller signed k."
```

---

## Task 3: build_candidates — generates the candidate inversion set

**Files:**
- Modify: `src/banjo/voice_leading.py`
- Modify: `tests/test_voice_leading.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_voice_leading.py`:

```python
from banjo.theory import parse_roman_numeral, parse_pitch_class
from banjo.voice_leading import build_candidates


class TestBuildCandidates:
    def test_triad_close_voicing_yields_three_inversions(self):
        # I in C major, close voicing, no explicit inversion -> 3 candidates
        parsed = parse_roman_numeral("I")
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="close", explicit_inversion=False,
        )
        assert len(candidates) == 3
        # Inversion 0: [60, 64, 67] (root position)
        assert sorted(candidates[0]) == [60, 64, 67]

    def test_seventh_chord_yields_four_inversions(self):
        # I7 in C major, close voicing -> 4 candidates (root, 1st, 2nd, 3rd)
        parsed = parse_roman_numeral("I7")
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="close", explicit_inversion=False,
        )
        assert len(candidates) == 4

    def test_thirteenth_chord_capped_at_four_inversions(self):
        # V13 has 7 notes; cap = min(3, N-1) = min(3, 6) = 3, so 4 candidates
        parsed = parse_roman_numeral("V13")
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="close", explicit_inversion=False,
        )
        assert len(candidates) == 4
        # Bottom note pitch class of every candidate must be a chord tone (R/3/5/7)
        # of V in C: G=7, B=11, D=2, F=5
        for cand in candidates:
            assert min(cand) % 12 in {7, 11, 2, 5}

    def test_rootless_seventh_yields_three_candidates(self):
        # I7 rootless: N (post-voicing) = 3, so candidates {0, 1, 2}
        parsed = parse_roman_numeral("I7")
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="rootless", explicit_inversion=False,
        )
        assert len(candidates) == 3
        # Each candidate has 3 notes (root dropped after inversion)
        for cand in candidates:
            assert len(cand) == 3

    def test_explicit_inversion_yields_single_candidate(self):
        # V64 with explicit_inversion=True -> candidate set is {2} only
        parsed = parse_roman_numeral("V64")  # parses to inversion 2
        candidates = build_candidates(
            parsed, parse_pitch_class("C"), "major", octave=4,
            voicing="close", explicit_inversion=True,
        )
        assert len(candidates) == 1
        # V at 2nd inversion close at octave=4 = D-G-B with D rotated up = [74, 79, 83].
        # build_chord applies inversion by rotating the lowest note up an octave
        # (theory.py: `notes[0] += 12; notes.sort()`), so V's root-position [67,71,74]
        # becomes [71,74,79] at 1st inv and [74,79,83] at 2nd inv.
        assert sorted(candidates[0]) == [74, 79, 83]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_voice_leading.py::TestBuildCandidates -v`
Expected: FAIL — `ImportError: cannot import name 'build_candidates'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/banjo/voice_leading.py`:

```python
import dataclasses

from banjo.theory import ParsedNumeral, build_chord
from banjo.voicings import VoicingName, apply_voicing


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_voice_leading.py -v`
Expected: PASS — 14 passed (9 prior + 5 new).

- [ ] **Step 5: Commit**

```bash
git add src/banjo/voice_leading.py tests/test_voice_leading.py
git commit -m "Add build_candidates for voice-leading inversion expansion

Caps at min(3, N-1) so 9/11/13 extensions never land in the bass.
Respects explicit_inversion by returning a single-element set."
```

---

## Task 4: apply_voicing purity regression

**Files:**
- Modify: `tests/test_voicings.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_voicings.py`:

```python
class TestApplyVoicingPurity:
    """
    Voice leading depends on apply_voicing being a pure function of
    (notes, voicing). If this regresses, voice-leading determinism breaks
    silently. See spec: docs/superpowers/specs/2026-04-28-voice-leading-design.md
    """

    def test_same_input_same_output(self):
        notes = [60, 64, 67, 71]
        for voicing in ("close", "drop2", "drop3", "drop2and4", "spread", "rootless"):
            r1 = apply_voicing(list(notes), voicing)
            r2 = apply_voicing(list(notes), voicing)
            assert r1 == r2, f"apply_voicing({notes!r}, {voicing!r}) not deterministic"

    def test_input_not_mutated(self):
        notes = [60, 64, 67, 71]
        original = list(notes)
        for voicing in ("close", "drop2", "drop3", "drop2and4", "spread", "rootless"):
            apply_voicing(notes, voicing)
            assert notes == original, f"apply_voicing mutated input under voicing={voicing!r}"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_voicings.py::TestApplyVoicingPurity -v`
Expected: PASS — 2 passed. (`apply_voicing` is already pure; this is a regression guard.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_voicings.py
git commit -m "Add apply_voicing purity regression test

Voice leading depends on apply_voicing being a pure function of
(notes, voicing). Lock that property so future refactors can't break
voice-leading determinism silently."
```

---

## Task 5: Wire voice_lead through GenerationRequest and midi_writer

**Files:**
- Modify: `src/banjo/midi_writer.py`
- Modify: `tests/test_midi_writer.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_midi_writer.py` (read the existing file first to match its style and imports):

```python
class TestVoiceLead:
    def test_voice_lead_defaults_false_unchanged_behavior(self, tmp_path):
        # Without voice_lead, V after I lands at root position close = [67, 71, 74]
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V", duration_beats=4),
            ],
        )
        result = generate(request, tmp_path)
        assert sorted(result.resolved[1]["midi"]) == [67, 71, 74]

    def test_voice_lead_true_picks_smoothest_inversion(self, tmp_path):
        # Worked example: I -> V with voice_lead lands V at 1st inv, k=-1: [59,62,67]
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        assert sorted(result.resolved[1]["midi"]) == [59, 62, 67]

    def test_first_chord_unchanged_with_voice_lead(self, tmp_path):
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        spec = ChordSpec(numeral="I", duration_beats=4, voicing="close")
        off = generate(
            GenerationRequest(key_center="C", scale_type="major", bpm=120, chords=[spec]),
            tmp_path / "off",
        )
        on = generate(
            GenerationRequest(
                key_center="C", scale_type="major", bpm=120, chords=[spec],
                voice_lead=True,
            ),
            tmp_path / "on",
        )
        assert off.resolved[0]["midi"] == on.resolved[0]["midi"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_midi_writer.py::TestVoiceLead -v`
Expected: FAIL — `TypeError: GenerationRequest.__init__() got an unexpected keyword argument 'voice_lead'`

- [ ] **Step 3: Modify GenerationRequest and the chord loop in `src/banjo/midi_writer.py`**

Add the `voice_lead` field to `GenerationRequest` (after `seed`):

```python
@dataclass
class GenerationRequest:
    key_center: str
    scale_type: str
    bpm: int
    chords: list[ChordSpec]
    octave: int = 4
    time_signature: str = "4/4"
    humanize: HumanizeSpec = field(default_factory=HumanizeSpec)
    seed: int | None = None
    voice_lead: bool = False
    filename: str | None = None
    prompt_context: str | None = None
    generation_notes: str | None = None
```

In `generate()`, replace the existing chord-resolution loop (currently lines ~83–91 — the loop that produces `resolved_chords`) with the voice-lead-aware version:

```python
    # Add this import near the top with the other banjo imports:
    # from banjo.voice_leading import build_candidates, choose_voicing_position

    # Resolve every chord into MIDI notes.
    resolved_chords: list[tuple[ChordSpec, ParsedNumeral, ResolvedChord, list[int]]] = []
    previous_voiced: list[int] | None = None
    for spec in request.chords:
        parsed = parse_roman_numeral(spec.numeral)
        # Track explicitness BEFORE overriding so voice leading respects user intent.
        explicit_inversion = parsed.inversion > 0 or spec.inversion is not None
        if spec.inversion is not None:
            parsed.inversion = spec.inversion
        chord = build_chord(parsed, key_pc, request.scale_type, octave=request.octave)

        if request.voice_lead and previous_voiced is not None:
            candidates = build_candidates(
                parsed, key_pc, request.scale_type, request.octave,
                spec.voicing, explicit_inversion,
            )
            voiced = choose_voicing_position(candidates, previous_voiced)
        else:
            voiced = apply_voicing(list(chord.midi_notes), spec.voicing)

        resolved_chords.append((spec, parsed, chord, voiced))
        previous_voiced = voiced
```

Also add the import at the top:

```python
from banjo.voice_leading import build_candidates, choose_voicing_position
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_midi_writer.py -v`
Expected: PASS — all existing tests still pass plus the 3 new `TestVoiceLead` tests.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `.venv/bin/pytest -q`
Expected: PASS — full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/banjo/midi_writer.py tests/test_midi_writer.py
git commit -m "Wire voice_lead into GenerationRequest and the chord loop

Defaults to false; opt-in path calls build_candidates +
choose_voicing_position. The off path is byte-identical to today
because the voice-leading branch is skipped entirely."
```

---

## Task 6: Plumb voice_lead through the MCP server

**Files:**
- Modify: `src/banjo/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_server.py` (read the file first for style/imports):

```python
class TestVoiceLeadPlumbing:
    def test_voice_lead_in_schema_with_default_false(self):
        from banjo.mcp_server import GENERATE_MIDI_PROGRESSION_SCHEMA
        prop = GENERATE_MIDI_PROGRESSION_SCHEMA["properties"].get("voice_lead")
        assert prop is not None, "voice_lead missing from schema"
        assert prop["type"] == "boolean"
        assert prop["default"] is False

    def test_handler_passes_voice_lead_true_through(self):
        from banjo.mcp_server import _build_generation_request
        req = _build_generation_request({
            "key_center": "C", "scale_type": "major", "bpm": 120,
            "chords": [{"numeral": "I", "duration_beats": 4}],
            "voice_lead": True,
        })
        assert req.voice_lead is True

    def test_handler_defaults_voice_lead_to_false(self):
        from banjo.mcp_server import _build_generation_request
        req = _build_generation_request({
            "key_center": "C", "scale_type": "major", "bpm": 120,
            "chords": [{"numeral": "I", "duration_beats": 4}],
        })
        assert req.voice_lead is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_mcp_server.py::TestVoiceLeadPlumbing -v`
Expected: FAIL — `KeyError: 'voice_lead'` (schema test) / `AttributeError` or `False` mismatch (handler tests).

- [ ] **Step 3: Add `voice_lead` to the schema**

In `src/banjo/mcp_server.py`, inside `GENERATE_MIDI_PROGRESSION_SCHEMA["properties"]`, add (place it logically near `seed`, before `filename`):

```python
        "voice_lead": {
            "type": "boolean",
            "default": False,
            "description": (
                "When true, after each chord is built and voiced, the chord's "
                "inversion and octave register are jointly chosen to minimize "
                "voice motion from the previous chord. Preserves the per-chord "
                "voicing (drop2 stays drop2, etc.). Respects explicit inversions "
                "(e.g. 'V64' or inversion=2) — those are pinned and only the "
                "octave shift is optimized. Off by default; enabling it makes "
                "consecutive chords flow smoothly instead of jumping registers."
            ),
        },
```

- [ ] **Step 4: Plumb `voice_lead` through `_build_generation_request`**

In `src/banjo/mcp_server.py`, update the `return GenerationRequest(...)` call in `_build_generation_request` to pass `voice_lead`:

```python
    return GenerationRequest(
        key_center=arguments["key_center"],
        scale_type=arguments["scale_type"],
        bpm=int(arguments["bpm"]),
        chords=chord_specs,
        octave=int(arguments.get("octave", 4)),
        time_signature=arguments.get("time_signature", "4/4"),
        humanize=humanize,
        seed=arguments.get("seed"),
        voice_lead=bool(arguments.get("voice_lead", False)),
        filename=arguments.get("filename"),
        prompt_context=arguments.get("prompt_context"),
        generation_notes=arguments.get("generation_notes"),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_mcp_server.py -v`
Expected: PASS — all prior tests plus the 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add src/banjo/mcp_server.py tests/test_mcp_server.py
git commit -m "Expose voice_lead via the MCP tool schema

Adds the boolean field to generate_midi_progression's input schema
and plumbs it through _build_generation_request. Default false."
```

---

## Task 7: End-to-end behavior tests

**Files:**
- Modify: `tests/test_midi_writer.py`

These are correctness/edge-case tests against the wired pipeline.

- [ ] **Step 1: Write the test for voicing preservation under drop2**

Append to `TestVoiceLead` in `tests/test_midi_writer.py`:

```python
    def test_voicing_preservation_drop2_keeps_wide_gap(self, tmp_path):
        """
        Strongest correctness signal in the suite: if the inversion+k
        expansion ever shifts individual notes instead of the whole chord,
        drop2's signature wide gap collapses. If this test fails, the
        pipeline order (build_chord -> apply_voicing -> shift) is wrong.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I7", duration_beats=4, voicing="drop2"),
                ChordSpec(numeral="vi7", duration_beats=4, voicing="drop2"),
                ChordSpec(numeral="ii7", duration_beats=4, voicing="drop2"),
                ChordSpec(numeral="V7", duration_beats=4, voicing="drop2"),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        for chord in result.resolved:
            notes = sorted(chord["midi"])
            gaps = [notes[i + 1] - notes[i] for i in range(len(notes) - 1)]
            max_gap = max(gaps)
            # Drop2 always opens a gap > a major 7th (>11 semitones is conservative;
            # close-position max gap for any 7th chord is at most 4 semitones).
            assert max_gap >= 8, (
                f"drop2 voicing collapsed for {chord['numeral']}: "
                f"notes={notes}, gaps={gaps}, max_gap={max_gap}. "
                f"Pipeline is likely shifting individual notes instead of the whole chord."
            )
```

- [ ] **Step 2: Run it to verify it passes**

Run: `.venv/bin/pytest tests/test_midi_writer.py::TestVoiceLead::test_voicing_preservation_drop2_keeps_wide_gap -v`
Expected: PASS.

- [ ] **Step 3: Write the explicit-inversion test (V64)**

Append to `TestVoiceLead`:

```python
    def test_explicit_inversion_pinned_but_k_still_optimized(self, tmp_path):
        """
        V64 with voice_lead on: inversion stays 2 AND k is the score-optimizing
        choice among the 5 candidates at that inversion. If a regression pins
        k=0 when inversion is explicit, this test catches it.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V64", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        v_notes = sorted(result.resolved[1]["midi"])
        # V at 2nd inv close (octave=4) = [74, 79, 83]. Previous = [60, 64, 67].
        # build_candidates returns one candidate (inversion pinned to 2);
        # choose_voicing_position then picks k:
        #   k=0  [74,79,83]: 7+12+16 = 35
        #   k=-1 [62,67,71]: 2+0+4   = 6  <- winner
        #   k=-2 [50,55,59]: 10+5+1  = 16
        # k=-1 wins. Inversion stayed at 2 (pinned), but k was still optimized.
        assert v_notes == [62, 67, 71]
        # Inversion preserved: pitch classes are D-G-B = {2, 7, 11}
        assert sorted(set(n % 12 for n in v_notes)) == [2, 7, 11]
```

- [ ] **Step 4: Write the extension cap test (V13 never in 9/11/13 bass)**

Append to `TestVoiceLead`:

```python
    def test_v13_never_lands_with_extension_in_bass(self, tmp_path):
        """V13's bass note must be a chord tone (R/3/5/7), never an extension (9/11/13)."""
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="V13", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        bottom_pc = min(result.resolved[1]["midi"]) % 12
        # V in C: chord tones are G(7), B(11), D(2), F(5).
        # Extensions: A(9), C(0), E(4) - these must NOT be the bass.
        assert bottom_pc in {7, 11, 2, 5}, (
            f"V13 landed with pc {bottom_pc} in bass; expected a chord tone (7,11,2,5)"
        )
```

- [ ] **Step 5: Write the rootless cross-voice-count sanity test**

Append to `TestVoiceLead`:

```python
    def test_rootless_after_close_does_not_crash(self, tmp_path):
        """
        Mixing voice counts across chords (close=4 voices, rootless 7th=3 voices)
        should still produce a sensible result. Voice leading only compares
        candidates of the *same* chord, so the cross-chord count mismatch is
        only a sanity check that nothing blows up.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I7", duration_beats=4, voicing="close"),
                ChordSpec(numeral="ii7", duration_beats=4, voicing="rootless"),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        # rootless of ii7 -> 3 notes
        assert len(result.resolved[1]["midi"]) == 3
```

- [ ] **Step 6: Write the register stability test (chromatic mediant chain)**

Append to `TestVoiceLead`:

```python
    def test_register_stability_chromatic_mediant_chain(self, tmp_path):
        """
        Empirical bound: under a chromatic-mediant chain (large root motion,
        sympathetic to runaway drift), the lowest note across all chords stays
        within +/-12 semitones of the starting chord. Not algorithmically
        guaranteed; the score function naturally prefers smaller |k|.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="I", duration_beats=4),
                ChordSpec(numeral="bIII", duration_beats=4),
                ChordSpec(numeral="bVI", duration_beats=4),
                ChordSpec(numeral="III", duration_beats=4),
                ChordSpec(numeral="I", duration_beats=4),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        starting_lowest = min(result.resolved[0]["midi"])
        for chord in result.resolved:
            lowest = min(chord["midi"])
            assert abs(lowest - starting_lowest) <= 12, (
                f"Chord {chord['numeral']} drifted to lowest={lowest} "
                f"from start={starting_lowest}"
            )
```

- [ ] **Step 7: Write the determinism test**

Append to `TestVoiceLead`:

```python
    def test_voice_lead_is_deterministic(self, tmp_path):
        """Same input twice -> identical resolved metadata, byte-for-byte."""
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate

        def make_request():
            return GenerationRequest(
                key_center="C", scale_type="major", bpm=120,
                chords=[
                    ChordSpec(numeral="I", duration_beats=4),
                    ChordSpec(numeral="vi", duration_beats=4),
                    ChordSpec(numeral="IV", duration_beats=4),
                    ChordSpec(numeral="V", duration_beats=4),
                ],
                voice_lead=True,
            )

        r1 = generate(make_request(), tmp_path / "a")
        r2 = generate(make_request(), tmp_path / "b")
        for c1, c2 in zip(r1.resolved, r2.resolved):
            assert c1["midi"] == c2["midi"]
```

- [ ] **Step 8: Write the test for ChordSpec.inversion field as the explicit source**

Append to `TestVoiceLead`. This covers the *other* source of explicit inversion (the `inversion` field on `ChordSpec`), distinct from numeral shorthand like `V64`. Both flow through the same `explicit_inversion` flag, but a dedicated test guards against future refactors that might handle them differently.

```python
    def test_chordspec_inversion_field_pins_inversion(self, tmp_path):
        """
        ChordSpec.inversion=1 explicitly forces 1st inversion even when root
        would score lower. Distinct from V64 (which encodes inversion in the
        numeral string); this test guards the second source of explicit-
        inversion intent.
        """
        from banjo.midi_writer import ChordSpec, GenerationRequest, generate
        request = GenerationRequest(
            key_center="C", scale_type="major", bpm=120,
            chords=[
                ChordSpec(numeral="vi", duration_beats=4),
                ChordSpec(numeral="V", duration_beats=4, inversion=1),
            ],
            voice_lead=True,
        )
        result = generate(request, tmp_path)
        v_notes = sorted(result.resolved[1]["midi"])
        # Previous (vi close) = [69, 72, 76]. V 1st inv close = B-D-G = [71, 74, 79].
        # k=0 score = 1+2+3 = 6; k=-1 score = 10+7+2 = 19; k=+1 score = 7+10+15 = 32.
        # k=0 wins among the inversion=1 candidates -> [71, 74, 79].
        # (Unrestricted, V root k=0 [67,71,74] would score 2+1+2 = 5 and win;
        # the inversion=1 must override that.)
        assert v_notes == [71, 74, 79]
        # Pitch classes are B-D-G = {2, 7, 11} (1st inversion preserved)
        assert sorted(set(n % 12 for n in v_notes)) == [2, 7, 11]
```

- [ ] **Step 9: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: PASS — full suite green, including the new `TestVoiceLead` tests.

- [ ] **Step 10: Commit**

```bash
git add tests/test_midi_writer.py
git commit -m "Add end-to-end voice-leading behavior tests

Covers voicing preservation under drop2 (the strongest pipeline-order
signal), explicit-inversion pinning with k still optimized, the
extension cap on V13, rootless cross-voice-count sanity, register
stability under a chromatic-mediant chain, and determinism."
```

---

## Self-review checklist

Before declaring the plan ready, verify:

- [ ] Every spec section has a task implementing it (algorithm → Tasks 1–3, midi_writer integration → Task 5, MCP plumbing → Task 6, tests → Tasks 4 + 7).
- [ ] No placeholders ("TBD", "implement later", "similar to Task N", etc.).
- [ ] Function names match across tasks: `_voicing_distance`, `choose_voicing_position`, `build_candidates` are used consistently.
- [ ] Every step that changes code shows the actual code.
- [ ] Every test step shows actual test code, not "write tests for X."
- [ ] Each task ends with a single commit.
- [ ] The `voice_lead=False` path is mechanically unchanged (the loop in Task 5 only adds an `if request.voice_lead and previous_voiced is not None:` branch — the else is the existing code).
