# Songwriter Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `rootless` from the voicing enum into an explicit per-chord boolean, add `max_octave` clamping, lower the default octave to 3, and rewrite all tool descriptions away from jazz pedagogy framing.

**Architecture:** Two files change: `midi_writer.py` (dataclasses + pipeline) and `mcp_server.py` (schema + validation + descriptions). `voicings.py` and `voice_leading.py` are untouched. The new pipeline order is: build → apply_voicing → voice_lead → rootless → max_octave_clamp.

**Tech Stack:** Python 3.11+, plain dataclasses (no Pydantic), mido, pytest.

---

## File Map

| File | Change |
|------|--------|
| `src/banjo/midi_writer.py` | Add `rootless: bool = False` to `ChordSpec`; add `max_octave: int = 5` to `GenerationRequest`; change `octave` default from `4` to `3`; implement rootless post-voicing step; implement `_clamp_to_max_octave`; document pipeline order inline |
| `src/banjo/mcp_server.py` | Remove `"rootless"` from voicing enum; add `rootless` bool field per chord; add `max_octave` field; change octave default to `3`; rewrite descriptions; add migration error + spread+rootless validation in `_build_generation_request` |
| `tests/test_midi_writer.py` | Update `test_sidecar_contains_metadata`: change `voicing="rootless"` to `rootless=True` on `ChordSpec`; add new tests for rootless bool and max_octave |
| `tests/test_mcp_server.py` | Add validation tests; update any existing args that pass `voicing: "rootless"` |
| `tests/test_voice_leading.py` | Update `test_rootless_seventh_yields_three_candidates` to reflect new pipeline (rootless no longer passed to `build_candidates`) |

---

## Task 1: Add `rootless` field to `ChordSpec` and update the MIDI writer pipeline

**Files:**
- Modify: `src/banjo/midi_writer.py`
- Test: `tests/test_midi_writer.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `tests/test_midi_writer.py` inside `class TestMidiWriter`:

```python
def test_rootless_false_by_default(self, tmp_output):
    """ChordSpec.rootless defaults to False; all notes including root are present."""
    request = GenerationRequest(
        key_center="C", scale_type="major", bpm=120,
        chords=[ChordSpec("I", 4)],  # C major triad: C E G
        octave=3, filename="test_rootless_default",
    )
    result = generate(request, tmp_output)
    midi_notes = result.resolved[0]["midi"]
    # C major triad in octave 3 (Ableton C3=60): C3=60, E3=64, G3=67
    assert 60 in midi_notes  # root C must be present

def test_rootless_true_strips_root(self, tmp_output):
    """ChordSpec with rootless=True omits the root note."""
    request = GenerationRequest(
        key_center="C", scale_type="major", bpm=120,
        chords=[ChordSpec("Imaj7", 4, rootless=True)],  # Cmaj7: C E G B
        octave=3, filename="test_rootless_strips",
    )
    result = generate(request, tmp_output)
    midi_notes = result.resolved[0]["midi"]
    # Root C3=60 must be absent; chord should have 3 notes (E G B)
    assert 60 not in midi_notes
    assert len(midi_notes) == 3
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /Users/david/Github/banjo && uv run pytest tests/test_midi_writer.py::TestMidiWriter::test_rootless_false_by_default tests/test_midi_writer.py::TestMidiWriter::test_rootless_true_strips_root -v
```

Expected: `FAILED` — `ChordSpec.__init__() got an unexpected keyword argument 'rootless'`

- [ ] **Step 3: Add `rootless` to `ChordSpec` and implement the pipeline step**

In `src/banjo/midi_writer.py`, make these changes:

```python
# Change ChordSpec (was missing rootless):
@dataclass
class ChordSpec:
    """Per-chord input to the writer."""
    numeral: str
    duration_beats: float
    inversion: int | None = None
    voicing: VoicingName = "close"
    rootless: bool = False
```

Then in `generate()`, restructure the per-chord resolution block. Replace the existing block (lines 87–110) with:

```python
    for spec in request.chords:
        parsed = parse_roman_numeral(spec.numeral)
        explicit_inversion = parsed.inversion > 0 or spec.inversion is not None
        if spec.inversion is not None:
            parsed.inversion = spec.inversion
        chord = build_chord(parsed, key_pc, request.scale_type, octave=request.octave)

        # Step 1-2: apply voicing (voice-led or direct)
        if request.voice_lead and previous_voiced is not None:
            candidates = build_candidates(
                parsed, key_pc, request.scale_type, request.octave,
                spec.voicing, explicit_inversion,
            )
            chosen_inv, voiced = choose_voicing_position(candidates, previous_voiced)
            parsed.inversion = chosen_inv
        else:
            voiced = apply_voicing(list(chord.midi_notes), spec.voicing)

        # Step 3: rootless — strip root after voice leading so VL sees the full chord
        if spec.rootless:
            voiced = apply_voicing(voiced, "rootless")

        # Step 4: max_octave clamp — hard ceiling applied last
        voiced = _clamp_to_max_octave(voiced, request.max_octave)

        resolved_chords.append((spec, parsed, chord, voiced))
        previous_voiced = voiced
```

Add this helper function at the bottom of `midi_writer.py` (before `_auto_filename`):

```python
def _clamp_to_max_octave(notes: list[int], max_octave: int) -> list[int]:
    """Shift notes down by whole octaves until the lowest note is within max_octave.

    Uses Ableton convention: C3 = MIDI 60, so octave N lowest note = 12*(N+2).
    """
    if not notes:
        return notes
    lowest_octave = (min(notes) // 12) - 2  # Ableton: C3=60 → (60//12)-2 = 3
    if lowest_octave > max_octave:
        shift = (lowest_octave - max_octave) * 12
        return [n - shift for n in notes]
    return notes
```

- [ ] **Step 4: Run the new tests to confirm they pass**

```bash
uv run pytest tests/test_midi_writer.py::TestMidiWriter::test_rootless_false_by_default tests/test_midi_writer.py::TestMidiWriter::test_rootless_true_strips_root -v
```

Expected: `PASSED`

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
uv run pytest -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/banjo/midi_writer.py tests/test_midi_writer.py
git commit -m "Add rootless bool to ChordSpec; apply after voice leading in pipeline"
```

---

## Task 2: Add `max_octave` to `GenerationRequest` and change octave default to 3

**Files:**
- Modify: `src/banjo/midi_writer.py`
- Test: `tests/test_midi_writer.py`

- [ ] **Step 1: Write the failing tests**

Add to `class TestMidiWriter` in `tests/test_midi_writer.py`:

```python
def test_default_octave_is_3(self, tmp_output):
    """GenerationRequest.octave defaults to 3 (Ableton mid-low register)."""
    request = GenerationRequest(
        key_center="C", scale_type="major", bpm=120,
        chords=[ChordSpec("I", 4)],
        filename="test_default_octave",
    )
    # C major triad at octave 3 (Ableton C3=60): root = 60
    result = generate(request, tmp_output)
    assert min(result.resolved[0]["midi"]) == 60  # C3

def test_max_octave_clamps_chord_one_octave_above(self, tmp_output):
    """A chord one octave above max_octave is shifted down by one octave."""
    request = GenerationRequest(
        key_center="C", scale_type="major", bpm=120,
        chords=[ChordSpec("I", 4)],
        octave=6, max_octave=5,
        filename="test_max_octave_clamp_one",
    )
    result = generate(request, tmp_output)
    midi_notes = result.resolved[0]["midi"]
    # Root should be at octave 5 (C5=84), not 6 (C6=96)
    assert min(midi_notes) == 84  # C5

def test_max_octave_clamps_chord_several_octaves_above(self, tmp_output):
    """A chord several octaves above max_octave is shifted to land at max_octave."""
    request = GenerationRequest(
        key_center="C", scale_type="major", bpm=120,
        chords=[ChordSpec("I", 4)],
        octave=8, max_octave=5,
        filename="test_max_octave_clamp_many",
    )
    result = generate(request, tmp_output)
    midi_notes = result.resolved[0]["midi"]
    # Root should be at octave 5 (C5=84), not 8 (C8=120)
    assert min(midi_notes) == 84  # C5

def test_max_octave_does_not_clamp_chord_at_limit(self, tmp_output):
    """A chord at exactly max_octave passes through unchanged."""
    request = GenerationRequest(
        key_center="C", scale_type="major", bpm=120,
        chords=[ChordSpec("I", 4)],
        octave=5, max_octave=5,
        filename="test_max_octave_no_clamp",
    )
    result = generate(request, tmp_output)
    # Root C5=84 is at octave 5, which equals max_octave — no shift
    assert min(result.resolved[0]["midi"]) == 84  # C5

def test_max_octave_default_is_5(self):
    """GenerationRequest.max_octave defaults to 5."""
    request = GenerationRequest(
        key_center="C", scale_type="major", bpm=120,
        chords=[ChordSpec("I", 4)],
    )
    assert request.max_octave == 5
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_midi_writer.py::TestMidiWriter::test_default_octave_is_3 tests/test_midi_writer.py::TestMidiWriter::test_max_octave_clamps_chord_one_octave_above tests/test_midi_writer.py::TestMidiWriter::test_max_octave_clamps_chord_several_octaves_above tests/test_midi_writer.py::TestMidiWriter::test_max_octave_does_not_clamp_chord_at_limit tests/test_midi_writer.py::TestMidiWriter::test_max_octave_default_is_5 -v
```

Expected: `FAILED` — `GenerationRequest.__init__() got an unexpected keyword argument 'max_octave'` and octave default assertions fail.

- [ ] **Step 3: Update `GenerationRequest` dataclass**

In `src/banjo/midi_writer.py`, change `GenerationRequest`:

```python
@dataclass
class GenerationRequest:
    key_center: str
    scale_type: str
    bpm: int
    chords: list[ChordSpec]
    octave: int = 3          # changed from 4; Ableton C3=60 (mid-low register)
    time_signature: str = "4/4"
    humanize: HumanizeSpec = field(default_factory=HumanizeSpec)
    seed: int | None = None
    voice_lead: bool = False
    max_octave: int = 5      # new field; hard ceiling on chord register
    filename: str | None = None
    prompt_context: str | None = None
    generation_notes: str | None = None
```

- [ ] **Step 4: Run the new tests**

```bash
uv run pytest tests/test_midi_writer.py::TestMidiWriter::test_default_octave_is_3 tests/test_midi_writer.py::TestMidiWriter::test_max_octave_clamps_chord_one_octave_above tests/test_midi_writer.py::TestMidiWriter::test_max_octave_clamps_chord_several_octaves_above tests/test_midi_writer.py::TestMidiWriter::test_max_octave_does_not_clamp_chord_at_limit tests/test_midi_writer.py::TestMidiWriter::test_max_octave_default_is_5 -v
```

Expected: `PASSED`

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all previously passing tests still pass. (Tests that don't specify `octave` will now use 3, but none assert specific MIDI note values that depend on the default octave.)

- [ ] **Step 6: Commit**

```bash
git add src/banjo/midi_writer.py tests/test_midi_writer.py
git commit -m "Add max_octave to GenerationRequest; lower default octave from 4 to 3"
```

---

## Task 3: Add validation in `_build_generation_request`

**Files:**
- Modify: `src/banjo/mcp_server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_server.py`:

```python
def test_voicing_rootless_string_raises_migration_error(isolated_config_dir, tmp_path):
    """Passing voicing='rootless' (old API) raises a targeted migration error."""
    config.set_output_directory(tmp_path / "out")
    with pytest.raises(ValueError, match="rootless.*no longer a voicing option"):
        mcp_server.handle_generate_midi_progression({
            "key_center": "C",
            "scale_type": "major",
            "bpm": 120,
            "chords": [{"numeral": "I", "duration_beats": 4, "voicing": "rootless"}],
        })


def test_spread_plus_rootless_raises(isolated_config_dir, tmp_path):
    """voicing=spread combined with rootless=true raises a validation error."""
    config.set_output_directory(tmp_path / "out")
    with pytest.raises(ValueError, match="rootless.*spread"):
        mcp_server.handle_generate_midi_progression({
            "key_center": "C",
            "scale_type": "major",
            "bpm": 120,
            "chords": [{"numeral": "I", "duration_beats": 4, "voicing": "spread", "rootless": True}],
        })


def test_rootless_true_accepted(isolated_config_dir, tmp_path):
    """rootless=true is accepted as a separate field alongside a non-spread voicing."""
    out = tmp_path / "out"
    config.set_output_directory(out)
    result = mcp_server.handle_generate_midi_progression({
        "key_center": "C",
        "scale_type": "major",
        "bpm": 120,
        "chords": [{"numeral": "Imaj7", "duration_beats": 4, "rootless": True}],
    })
    assert "filepath" in result
    # Cmaj7 has 4 notes; rootless strips the root, leaving 3
    assert len(result["resolved"][0]["midi"]) == 3


def test_max_octave_field_accepted(isolated_config_dir, tmp_path):
    """max_octave field is accepted and passed through."""
    out = tmp_path / "out"
    config.set_output_directory(out)
    result = mcp_server.handle_generate_midi_progression({
        "key_center": "C",
        "scale_type": "major",
        "bpm": 120,
        "chords": [{"numeral": "I", "duration_beats": 4}],
        "octave": 7,
        "max_octave": 4,
    })
    # Chord placed at octave 7 then clamped to 4; root C4=72
    assert min(result["resolved"][0]["midi"]) == 72  # C4
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_mcp_server.py::test_voicing_rootless_string_raises_migration_error tests/test_mcp_server.py::test_spread_plus_rootless_raises tests/test_mcp_server.py::test_rootless_true_accepted tests/test_mcp_server.py::test_max_octave_field_accepted -v
```

Expected: `FAILED`

- [ ] **Step 3: Update `_build_generation_request` in `mcp_server.py`**

Replace the chord-parsing loop (the block that builds `chord_specs`) with:

```python
    chord_specs: list[ChordSpec] = []
    for i, c in enumerate(chords_raw):
        if not isinstance(c, dict):
            raise ValueError(f"chords[{i}] must be an object")
        if "numeral" not in c or "duration_beats" not in c:
            raise ValueError(f"chords[{i}] requires 'numeral' and 'duration_beats'")

        voicing = c.get("voicing", "close")
        # Migration guard: rootless was removed from the voicing enum in v0.3.0.
        if voicing == "rootless":
            raise ValueError(
                f"chords[{i}]: 'rootless' is no longer a voicing option — "
                "pass rootless: true alongside your chosen voicing "
                "(e.g. voicing: 'close', rootless: true)."
            )

        rootless = bool(c.get("rootless", False))
        if voicing == "spread" and rootless:
            raise ValueError(
                f"chords[{i}]: rootless: true cannot be combined with "
                "voicing: spread — spread is defined by its bass root."
            )

        chord_specs.append(ChordSpec(
            numeral=c["numeral"],
            duration_beats=float(c["duration_beats"]),
            inversion=c.get("inversion"),
            voicing=voicing,
            rootless=rootless,
        ))
```

Also update the `GenerationRequest` construction at the bottom of `_build_generation_request` to pass `max_octave`:

```python
    return GenerationRequest(
        key_center=arguments["key_center"],
        scale_type=arguments["scale_type"],
        bpm=int(arguments["bpm"]),
        chords=chord_specs,
        octave=int(arguments.get("octave", 3)),
        time_signature=arguments.get("time_signature", "4/4"),
        humanize=humanize,
        seed=arguments.get("seed"),
        voice_lead=bool(arguments.get("voice_lead", False)),
        max_octave=int(arguments.get("max_octave", 5)),
        filename=arguments.get("filename"),
        prompt_context=arguments.get("prompt_context"),
        generation_notes=arguments.get("generation_notes"),
    )
```

- [ ] **Step 4: Run the new tests**

```bash
uv run pytest tests/test_mcp_server.py::test_voicing_rootless_string_raises_migration_error tests/test_mcp_server.py::test_spread_plus_rootless_raises tests/test_mcp_server.py::test_rootless_true_accepted tests/test_mcp_server.py::test_max_octave_field_accepted -v
```

Expected: `PASSED`

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/banjo/mcp_server.py tests/test_mcp_server.py
git commit -m "Add rootless bool and max_octave to MCP schema; add migration error for voicing=rootless"
```

---

## Task 4: Update the MCP schema and rewrite all descriptions

**Files:**
- Modify: `src/banjo/mcp_server.py`

No new tests needed here — the schema changes are validated by the integration tests already passing. The existing `test_generate_full_args` test exercises the voicing field and will catch schema breakage.

- [ ] **Step 1: Update the voicing enum in `GENERATE_MIDI_PROGRESSION_SCHEMA`**

Find the `"voicing"` property inside the chord items object and replace it:

```python
                    "voicing": {
                        "type": "string",
                        "enum": ["close", "drop2", "drop3", "drop2and4", "spread"],
                        "default": "close",
                        "description": (
                            "Voicing transformation applied to the chord. "
                            "'close' — stacked thirds, compact and clear. "
                            "'drop2' — second-from-top voice dropped an octave, slightly warmer. "
                            "'drop3' — third-from-top voice dropped an octave, fuller spread. "
                            "'drop2and4' — second and fourth from top dropped an octave, wide and open. "
                            "'spread' — root dropped an octave below the upper structure."
                        ),
                    },
                    "rootless": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Omit the root note from the chord. Only use this when a separate "
                            "bass instrument is playing the root — not appropriate for solo piano "
                            "or standalone DAW clips. Cannot be combined with voicing: spread."
                        ),
                    },
```

- [ ] **Step 2: Update the `octave` field**

Find `"octave"` in the schema and replace:

```python
        "octave": {
            "type": "integer",
            "minimum": 0,
            "maximum": 9,
            "default": 3,
            "description": (
                "Root octave. Follows Ableton convention: C3 = MIDI 60 (middle C). "
                "Default 3 puts chords in a comfortable mid-low piano register. "
                "For most songwriting, stay between 2 and 4. "
                "Above 5 puts chords in melody territory."
            ),
        },
```

- [ ] **Step 3: Add the `max_octave` field to the schema**

Add after the `octave` field:

```python
        "max_octave": {
            "type": "integer",
            "minimum": 0,
            "maximum": 9,
            "default": 5,
            "description": (
                "Hard ceiling on chord register (Ableton convention). "
                "Any chord whose lowest note falls above this octave is shifted down "
                "by whole octaves until it is at or below max_octave. "
                "Applied after voice leading. Default 5 prevents runaway high voicings."
            ),
        },
```

- [ ] **Step 4: Rewrite the top-level tool description**

In `list_tools()`, replace the `description` on `generate_midi_progression`:

```python
        Tool(
            name="generate_midi_progression",
            description=(
                "Generate a MIDI chord progression for a solo producer or songwriter "
                "to load into a DAW. Chords are self-contained — the root is always "
                "included unless rootless is explicitly set to true. "
                "Returns the MIDI file path, sidecar markdown path, resolved chord "
                "metadata (per-chord pitches, voicing, inversion), and total duration. "
                "Handles secondary dominants, modal mixture, half-diminished chords, "
                "alterations, and five voicing styles — see the inputSchema for the full grammar. "
                "Default octave 3 and max_octave 5 keep chords in a comfortable piano register."
            ),
            inputSchema=GENERATE_MIDI_PROGRESSION_SCHEMA,
        ),
```

- [ ] **Step 5: Run the full suite to confirm nothing broke**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/banjo/mcp_server.py
git commit -m "Rewrite MCP schema descriptions for songwriter context; remove rootless from voicing enum"
```

---

## Task 5: Update existing tests that use the old `voicing="rootless"` API

**Files:**
- Modify: `tests/test_midi_writer.py`
- Modify: `tests/test_voice_leading.py`

These tests still pass (the old code path still works at the Python level), but they test behaviour that no longer matches the intended design. Update them to use the new API.

- [ ] **Step 1: Update `test_sidecar_contains_metadata` in `test_midi_writer.py`**

Find line:
```python
chords=[ChordSpec("Imaj9", 4, voicing="rootless")],
```

Replace with:
```python
chords=[ChordSpec("Imaj9", 4, rootless=True)],
```

No assertions change — the test checks `generation_notes` text and metadata, not the voicing field value.

- [ ] **Step 2: Update `test_rootless_seventh_yields_three_candidates` in `test_voice_leading.py`**

Find the test (around line 114). The old test passed `voicing="rootless"` to `build_candidates`, testing how voice leading handled rootless voicings. Under the new pipeline, `build_candidates` is never called with `"rootless"` — rootless is stripped after voice leading. Update the test to reflect this:

```python
def test_rootless_seventh_yields_three_candidates(self):
    # Under the new pipeline, voice leading sees the full chord (including root).
    # Rootless is applied AFTER voice leading. So for a 7th chord with close voicing,
    # build_candidates should produce 4 candidates (one per inversion of the 4-note chord).
    parsed = parse_roman_numeral("Imaj7")
    candidates = build_candidates(
        parsed, parse_pitch_class("C"), "major", octave=4,
        voicing="close", explicit_inversion=False,
    )
    # Imaj7 has 4 notes → 4 inversion candidates
    assert len(candidates) == 4
```

- [ ] **Step 3: Run the full suite**

```bash
uv run pytest -v
```

Expected: all 107+ tests pass (107 original + the new tests added in Tasks 1–3).

- [ ] **Step 4: Commit**

```bash
git add tests/test_midi_writer.py tests/test_voice_leading.py
git commit -m "Update tests to use new rootless bool API; align voice leading test with new pipeline"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Extract rootless from voicing enum; add as per-chord bool | Task 1 (ChordSpec), Task 4 (schema) |
| spread + rootless → validation error | Task 3 |
| Migration error for `voicing: "rootless"` | Task 3 |
| Both checks in `_build_generation_request` | Task 3 |
| Rootless applied after voice_lead in pipeline | Task 1 |
| max_octave field (default 5) | Task 2 (dataclass), Task 3 (MCP), Task 4 (schema) |
| max_octave clamp semantics (whole octaves, after voice_lead) | Task 1 (`_clamp_to_max_octave`) |
| Default octave changed from 4 to 3 | Task 2 (dataclass), Task 3 (MCP default), Task 4 (schema default) |
| Ableton convention documented in field descriptions | Task 4 |
| Tool description rewritten for solo producer context | Task 4 |
| Voicing descriptions rewritten without jazz framing | Task 4 |
| Test matrix: rootless variants, max_octave edge cases | Tasks 1, 2, 3 |

All requirements covered. No gaps.
