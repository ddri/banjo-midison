# Phase 2: MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the existing `generate()` function in `src/banjo/midi_writer.py` as a stdio-transport MCP server exposing two tools (`generate_midi_progression`, `set_output_directory`) for use from Claude Desktop.

**Architecture:** Two new modules. `banjo.config` reads/writes a persistent JSON config at `~/.banjo/config.json` (currently just `output_directory`). `banjo.mcp_server` defines the MCP server using the official Python `mcp` SDK's low-level `Server` API. Tool handlers are pure functions on plain dicts so they can be unit-tested without spinning up the JSON-RPC transport. The MCP wiring is a thin adapter — all music-theory logic stays in the Phase 1 modules, untouched.

**Tech Stack:** Python 3.11+, `mcp>=1.0` (official Python MCP SDK), `mido` (already in Phase 1), `pytest`.

**Design decisions (confirmed by user):**
- Expose all 11 `GenerationRequest` fields. `key_center`, `scale_type`, `bpm`, `chords` required; rest optional with sensible defaults.
- Persistent config at `~/.banjo/config.json`; default output directory `~/Music/banjo/` if not set, created lazily on first write.
- Return full payload (filepath, sidecar_path, resolved, total_beats) so the model can reason about what it just wrote.
- Raise MCP-level tool errors on bad input — let Claude Desktop surface them inline.
- `logging.basicConfig(stream=sys.stderr, level=logging.INFO)` from the start; per-tool-call log lines.
- Add a `banjo-mcp` console script entry point so the Claude Desktop config snippet can point at a stable command.

---

## Preconditions

The repo currently has Phase 1 source files all untracked (the only commit is `f54c308` which contained `files.zip`, now deleted). Before starting Phase 2, commit the Phase 1 code:

```bash
cd /Users/david/Github/banjo
git rm --cached files.zip 2>/dev/null  # already deleted on disk
git add .gitignore pyproject.toml README.md src/banjo tests
git status  # confirm: no .DS_Store, no .venv/, no output/, no .claude/
git commit -m "Phase 1: extract source from zip and flatten layout"
```

If `.claude/` should be committed (project-specific agent config), add it; otherwise leave untracked. `.DS_Store`, `.venv/`, `output/` should remain ignored.

---

## File Structure

**Created:**
- `src/banjo/config.py` — `~/.banjo/config.json` read/write helpers. Public API: `get_output_directory()`, `set_output_directory(path)`, `DEFAULT_OUTPUT_DIR`.
- `src/banjo/mcp_server.py` — MCP server bootstrap, tool schema definitions, pure handler functions, and `main()` entry point.
- `tests/test_config.py` — tests for config helpers (using pytest's `tmp_path` + `monkeypatch`).
- `tests/test_mcp_server.py` — tests for tool handler functions.

**Modified:**
- `pyproject.toml` — add `mcp>=1.0` dependency, add `banjo-mcp` script entry.
- `README.md` — add Phase 2 section with Claude Desktop config snippet.

**Untouched:** `theory.py`, `voicings.py`, `midi_writer.py`, `corpus.py`, all Phase 1 tests.

---

## Task 1: Config module — defaults and load

**Files:**
- Create: `src/banjo/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
"""Tests for ~/.banjo/config.json read/write helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from banjo import config


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR to a tmp path so tests don't touch ~/.banjo/."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".banjo")
    return tmp_path / ".banjo"


def test_default_output_directory_when_no_config(isolated_config_dir):
    # No config file exists yet.
    assert not (isolated_config_dir / "config.json").exists()
    result = config.get_output_directory()
    assert result == Path.home() / "Music" / "banjo"
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'banjo.config'`.

- [ ] **Step 3: Implement minimal config.py**

```python
# src/banjo/config.py
"""
Persistent configuration for banjo.

Stored at ~/.banjo/config.json. Currently tracks only the output directory,
but the schema is extensible.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".banjo"
DEFAULT_OUTPUT_DIR = Path.home() / "Music" / "banjo"


def _config_file() -> Path:
    return CONFIG_DIR / "config.json"


def _load() -> dict:
    """Load the config file, returning {} if it doesn't exist or is unreadable."""
    f = _config_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def get_output_directory() -> Path:
    """Return the configured output directory, falling back to the default."""
    cfg = _load()
    raw = cfg.get("output_directory")
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_OUTPUT_DIR
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_config.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/banjo/config.py tests/test_config.py
git commit -m "Add banjo.config with default output directory"
```

---

## Task 2: Config module — set and persist

**Files:**
- Modify: `src/banjo/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for set_output_directory**

Append to `tests/test_config.py`:

```python
def test_set_output_directory_persists(isolated_config_dir, tmp_path):
    target = tmp_path / "studio_output"
    returned = config.set_output_directory(target)
    assert returned == target.resolve()

    # Persisted on disk.
    cfg_file = isolated_config_dir / "config.json"
    assert cfg_file.exists()
    data = json.loads(cfg_file.read_text())
    assert data["output_directory"] == str(target.resolve())

    # Subsequent get returns the same value.
    assert config.get_output_directory() == target.resolve()


def test_set_output_directory_creates_config_dir(isolated_config_dir, tmp_path):
    assert not isolated_config_dir.exists()
    config.set_output_directory(tmp_path / "out")
    assert isolated_config_dir.is_dir()


def test_set_output_directory_expands_tilde(isolated_config_dir):
    returned = config.set_output_directory("~/banjo_test_xyz")
    assert returned == (Path.home() / "banjo_test_xyz").resolve()
    assert "~" not in str(returned)


def test_get_output_directory_handles_corrupt_config(isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "config.json").write_text("not valid json {{{")
    # Should silently fall back to default rather than crash.
    assert config.get_output_directory() == Path.home() / "Music" / "banjo"
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/python -m pytest tests/test_config.py -v
```

Expected: 3 failures (`AttributeError: module 'banjo.config' has no attribute 'set_output_directory'`), 1 pre-existing pass, 1 already-passing (corrupt config — but may fail if not handled).

- [ ] **Step 3: Implement set_output_directory**

Append to `src/banjo/config.py`:

```python
def _save(cfg: dict) -> None:
    """Write config to disk, creating CONFIG_DIR if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _config_file().write_text(json.dumps(cfg, indent=2) + "\n")


def set_output_directory(path: str | Path) -> Path:
    """Persist the output directory to config. Returns the resolved absolute path."""
    resolved = Path(path).expanduser().resolve()
    cfg = _load()
    cfg["output_directory"] = str(resolved)
    _save(cfg)
    return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/python -m pytest tests/test_config.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/banjo/config.py tests/test_config.py
git commit -m "Add banjo.config.set_output_directory with persistence"
```

---

## Task 3: Add `mcp` dependency and entry point

**Files:**
- Modify: `pyproject.toml`
- Create: `src/banjo/mcp_server.py` (stub only)

This task adds the dep + script entry so subsequent tasks can build on a working install. The stub server lists the two tools but doesn't implement them yet.

- [ ] **Step 1: Modify pyproject.toml**

Replace the `[project]` and `[project.scripts]` sections in `pyproject.toml` with:

```toml
[project]
name = "banjo"
version = "0.1.0"
description = "MIDI chord progression generator from Roman numeral analysis."
requires-python = ">=3.11"
dependencies = [
    "mido>=1.3.0",
    "mcp>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[project.scripts]
banjo-corpus = "banjo.corpus:main"
banjo-mcp = "banjo.mcp_server:main"
```

(Other sections — `[build-system]`, `[tool.hatch.build.targets.wheel]`, `[tool.pytest.ini_options]` — unchanged.)

- [ ] **Step 2: Create stub mcp_server.py**

```python
# src/banjo/mcp_server.py
"""
MCP server wrapping banjo's MIDI generator.

Transport: stdio (for use from Claude Desktop or any MCP host).

Exposes:
  - generate_midi_progression: render a Roman numeral progression to MIDI.
  - set_output_directory: persist the output directory to ~/.banjo/config.json.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

logger = logging.getLogger("banjo.mcp")

server: Server = Server("banjo")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise the two banjo tools to the MCP host."""
    return [
        Tool(
            name="generate_midi_progression",
            description="(stub — implemented in a later task)",
            inputSchema={"type": "object"},
        ),
        Tool(
            name="set_output_directory",
            description="(stub — implemented in a later task)",
            inputSchema={"type": "object"},
        ),
    ]


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Reinstall to pick up the new dependency and entry point**

```
uv pip install -e ".[dev]"
```

Expected: `mcp` installed; `banjo==0.1.0` reinstalled.

- [ ] **Step 4: Smoke-test that the entry point loads**

```
.venv/bin/python -c "from banjo.mcp_server import server, list_tools; import asyncio; print([t.name for t in asyncio.run(list_tools())])"
```

Expected: `['generate_midi_progression', 'set_output_directory']`.

- [ ] **Step 5: Confirm Phase 1 tests still pass**

```
.venv/bin/python -m pytest -v
```

Expected: 54 + 5 = 59 passed (Phase 1 + Task 1/2 config tests).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/banjo/mcp_server.py
git commit -m "Add MCP server skeleton with mcp>=1.0 and banjo-mcp entry point"
```

---

## Task 4: `set_output_directory` tool handler

**Files:**
- Modify: `src/banjo/mcp_server.py`
- Create: `tests/test_mcp_server.py`

The MCP SDK does not validate inputs against the declared schema by default — handlers must validate defensively. We use the pattern: pure handler function on a dict, wired into the `@server.call_tool()` dispatcher.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mcp_server.py
"""Tests for MCP tool handlers (pure functions on dicts, no transport involved)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from banjo import config, mcp_server


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Redirect both CONFIG_DIR and the default output dir to tmp."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".banjo")
    monkeypatch.setattr(config, "DEFAULT_OUTPUT_DIR", tmp_path / "Music" / "banjo")
    return tmp_path


def test_set_output_directory_handler_persists(tmp_path):
    target = tmp_path / "studio"
    result = mcp_server.handle_set_output_directory({"path": str(target)})
    assert result == {"output_directory": str(target.resolve())}
    assert config.get_output_directory() == target.resolve()


def test_set_output_directory_missing_path_raises():
    with pytest.raises(ValueError, match="path"):
        mcp_server.handle_set_output_directory({})


def test_set_output_directory_non_string_raises():
    with pytest.raises(ValueError, match="string"):
        mcp_server.handle_set_output_directory({"path": 42})


def test_set_output_directory_empty_string_raises():
    with pytest.raises(ValueError, match="empty"):
        mcp_server.handle_set_output_directory({"path": ""})
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/python -m pytest tests/test_mcp_server.py -v
```

Expected: 4 failures (`AttributeError: module 'banjo.mcp_server' has no attribute 'handle_set_output_directory'`).

- [ ] **Step 3: Implement the handler and wire it into call_tool**

Replace the stub `list_tools` in `src/banjo/mcp_server.py` and add the handler + dispatcher. The full file becomes:

```python
# src/banjo/mcp_server.py
"""
MCP server wrapping banjo's MIDI generator.

Transport: stdio (for use from Claude Desktop or any MCP host).

Exposes:
  - generate_midi_progression: render a Roman numeral progression to MIDI.
  - set_output_directory: persist the output directory to ~/.banjo/config.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from banjo import config

logger = logging.getLogger("banjo.mcp")

server: Server = Server("banjo")


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

SET_OUTPUT_DIRECTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Absolute or ~-prefixed directory path. Created on first write. "
                "Persisted to ~/.banjo/config.json across server restarts."
            ),
        },
    },
    "required": ["path"],
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="generate_midi_progression",
            description="(stub — implemented in next task)",
            inputSchema={"type": "object"},
        ),
        Tool(
            name="set_output_directory",
            description=(
                "Set the directory where generated MIDI files are written. "
                "The setting is persisted to ~/.banjo/config.json across "
                "Claude Desktop restarts."
            ),
            inputSchema=SET_OUTPUT_DIRECTORY_SCHEMA,
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers (pure functions on dicts — testable without transport)
# ---------------------------------------------------------------------------

def handle_set_output_directory(arguments: dict) -> dict:
    """Validate args, persist the directory, return a confirmation payload."""
    if "path" not in arguments:
        raise ValueError("Missing required argument: path")
    path = arguments["path"]
    if not isinstance(path, str):
        raise ValueError(f"path must be a string, got {type(path).__name__}")
    if not path.strip():
        raise ValueError("path must not be empty")

    resolved = config.set_output_directory(path)
    logger.info("output directory set to %s", resolved)
    return {"output_directory": str(resolved)}


# ---------------------------------------------------------------------------
# MCP dispatcher
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info("tool call: %s args=%s", name, list(arguments.keys()))
    if name == "set_output_directory":
        result = handle_set_output_directory(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/python -m pytest tests/test_mcp_server.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full suite as a regression check**

```
.venv/bin/python -m pytest
```

Expected: 63 passed (54 Phase 1 + 5 config + 4 mcp_server).

- [ ] **Step 6: Commit**

```bash
git add src/banjo/mcp_server.py tests/test_mcp_server.py
git commit -m "Implement set_output_directory MCP tool"
```

---

## Task 5: `generate_midi_progression` tool — schema declaration

**Files:**
- Modify: `src/banjo/mcp_server.py`

Just declare the JSON schema and update `list_tools()`. Handler implementation comes in Task 6 (separate so the schema is locked down before handler logic).

- [ ] **Step 1: Import MODE_INTERVALS at the top of mcp_server.py**

Add this import alongside the existing `from banjo import config` line:

```python
from banjo.theory import MODE_INTERVALS
```

This sources the `scale_type` enum from a single point of truth — when
`theory.py` adds a new mode (e.g. "melodic_minor"), the MCP schema picks
it up automatically.

- [ ] **Step 2: Add the schema constant**

In `src/banjo/mcp_server.py`, add this above the existing `SET_OUTPUT_DIRECTORY_SCHEMA` constant:

```python
GENERATE_MIDI_PROGRESSION_SCHEMA = {
    "type": "object",
    "required": ["key_center", "scale_type", "bpm", "chords"],
    "properties": {
        "key_center": {
            "type": "string",
            "description": "Tonic note name. Examples: 'C', 'F#', 'Bb', 'Eb'.",
        },
        "scale_type": {
            "type": "string",
            "enum": sorted(MODE_INTERVALS.keys()),
            "description": "Mode/scale of the key.",
        },
        "bpm": {
            "type": "integer",
            "minimum": 1,
            "maximum": 999,
            "description": "Tempo in beats per minute.",
        },
        "chords": {
            "type": "array",
            "minItems": 1,
            "description": (
                "Ordered list of chords. Each chord is a Roman numeral plus "
                "duration in beats. See the README for the supported numeral grammar."
            ),
            "items": {
                "type": "object",
                "required": ["numeral", "duration_beats"],
                "properties": {
                    "numeral": {
                        "type": "string",
                        "description": (
                            "Roman numeral with optional extensions/alterations/inversions. "
                            "Examples: 'I', 'ii7', 'V13', 'V7b9', 'V7/vi', 'iiø', 'bVII', "
                            "'vii°', 'III+', 'V64'."
                        ),
                    },
                    "duration_beats": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "description": "Duration of this chord in beats.",
                    },
                    "inversion": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3,
                        "description": (
                            "Override inversion. 0 = root, 1 = first, 2 = second, "
                            "3 = third (only valid for seventh chords). Optional — if "
                            "the numeral itself encodes an inversion (e.g. 'V64'), "
                            "omit this."
                        ),
                    },
                    "voicing": {
                        "type": "string",
                        "enum": ["close", "drop2", "drop3", "drop2and4", "spread", "rootless"],
                        "default": "close",
                        "description": (
                            "Voicing transformation. 'close' = stack of thirds. "
                            "'drop2' = 2nd-from-top dropped an octave (jazz piano staple). "
                            "'rootless' = omit root (pianist's left-hand voicing when "
                            "a bassist plays the root). 'spread' = wide voicing for "
                            "piano LH/RH separation."
                        ),
                    },
                },
            },
        },
        "octave": {
            "type": "integer",
            "minimum": 0,
            "maximum": 9,
            "default": 4,
            "description": "Octave for the root note. 4 = middle-C octave (C4).",
        },
        "time_signature": {
            "type": "string",
            "default": "4/4",
            "description": "Time signature as 'N/D'. Examples: '4/4', '3/4', '6/8'.",
        },
        "humanize": {
            "type": "object",
            "description": "Optional velocity/timing humanization for a played-in feel.",
            "properties": {
                "velocity_range": {
                    "type": "integer", "minimum": 0, "maximum": 127, "default": 0,
                    "description": "Max +/- deviation from base_velocity per note.",
                },
                "timing_ms": {
                    "type": "integer", "minimum": 0, "default": 0,
                    "description": "Max +/- timing deviation per note in milliseconds.",
                },
                "base_velocity": {
                    "type": "integer", "minimum": 1, "maximum": 127, "default": 80,
                    "description": "Center velocity. 80 is a comfortable mezzo-forte default.",
                },
            },
        },
        "seed": {
            "type": "integer",
            "description": (
                "Random seed for reproducible humanization. Omit for non-deterministic. "
                "Always set this when iterating on a request — same seed = same MIDI bytes."
            ),
        },
        "filename": {
            "type": "string",
            "description": (
                "Output filename without the .mid extension. Auto-generated from "
                "key + progression + timestamp if omitted."
            ),
        },
        "prompt_context": {
            "type": "string",
            "description": (
                "Free-text description of what the user asked for. Written verbatim "
                "into the .md sidecar so the file is self-documenting in a DAW project."
            ),
        },
        "generation_notes": {
            "type": "string",
            "description": (
                "Free-text musical/harmonic notes about the choices made (voicing rationale, "
                "stylistic references, etc). Written verbatim into the .md sidecar."
            ),
        },
    },
}
```

- [ ] **Step 3: Update list_tools to use the new schema**

In `list_tools()`, replace the `generate_midi_progression` Tool entry:

```python
        Tool(
            name="generate_midi_progression",
            description=(
                "Generate a MIDI file from a Roman numeral chord progression. "
                "Returns the MIDI file path, sidecar markdown path, resolved chord "
                "metadata (per-chord pitches, voicing, inversion), and total duration. "
                "Use this whenever the user wants a chord progression rendered as a MIDI "
                "clip suitable for dragging into a DAW. The generator handles secondary "
                "dominants, modal mixture, half-diminished chords, alterations, and "
                "six voicing styles — see the inputSchema for the full grammar."
            ),
            inputSchema=GENERATE_MIDI_PROGRESSION_SCHEMA,
        ),
```

- [ ] **Step 4: Verify the server still loads and lists 2 tools**

```
.venv/bin/python -c "from banjo.mcp_server import list_tools; import asyncio; tools = asyncio.run(list_tools()); print([(t.name, len(t.inputSchema.get('properties', {}))) for t in tools])"
```

Expected: `[('generate_midi_progression', 11), ('set_output_directory', 1)]`.

- [ ] **Step 5: Commit**

```bash
git add src/banjo/mcp_server.py
git commit -m "Declare generate_midi_progression JSON schema"
```

---

## Task 6: `generate_midi_progression` handler — minimal happy path (TDD)

**Files:**
- Modify: `src/banjo/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_server.py`:

```python
def test_generate_minimal_args(isolated_config_dir, tmp_path):
    """Minimal valid args produce a MIDI file in the configured output dir."""
    out = tmp_path / "out"
    config.set_output_directory(out)

    result = mcp_server.handle_generate_midi_progression({
        "key_center": "C",
        "scale_type": "major",
        "bpm": 110,
        "chords": [
            {"numeral": "ii7", "duration_beats": 4},
            {"numeral": "V7", "duration_beats": 4},
            {"numeral": "Imaj7", "duration_beats": 8},
        ],
    })

    assert "filepath" in result
    assert "sidecar_path" in result
    assert "resolved" in result
    assert "total_beats" in result
    assert result["total_beats"] == 16
    assert Path(result["filepath"]).exists()
    assert Path(result["filepath"]).suffix == ".mid"
    assert Path(result["sidecar_path"]).exists()
    assert Path(result["sidecar_path"]).suffix == ".md"
    # Resolved metadata is a list of per-chord dicts.
    assert len(result["resolved"]) == 3
    assert result["resolved"][0]["numeral"] == "ii7"
    assert result["resolved"][0]["voicing"] == "close"  # default applied
```

- [ ] **Step 2: Run the test to verify it fails**

```
.venv/bin/python -m pytest tests/test_mcp_server.py::test_generate_minimal_args -v
```

Expected: `AttributeError: module 'banjo.mcp_server' has no attribute 'handle_generate_midi_progression'`.

- [ ] **Step 3: Implement the handler**

Add these imports to the top of `src/banjo/mcp_server.py` (after the existing `from banjo import config` line):

```python
from banjo.midi_writer import (
    ChordSpec,
    GenerationRequest,
    HumanizeSpec,
    generate,
)
```

Add the handler above the `call_tool` dispatcher:

```python
def handle_generate_midi_progression(arguments: dict) -> dict:
    """Validate args, build a GenerationRequest, generate the MIDI file, return payload."""
    request = _build_generation_request(arguments)
    output_dir = config.get_output_directory()
    result = generate(request, output_dir)
    logger.info(
        "generated %s (%d chords, %.1f beats) in %s",
        result.filepath.name, len(result.resolved), result.total_beats, output_dir,
    )
    return {
        "filepath": str(result.filepath),
        "sidecar_path": str(result.sidecar_path),
        "resolved": result.resolved,
        "total_beats": result.total_beats,
    }


def _build_generation_request(arguments: dict) -> GenerationRequest:
    """Translate the MCP arguments dict into a GenerationRequest dataclass."""
    for required in ("key_center", "scale_type", "bpm", "chords"):
        if required not in arguments:
            raise ValueError(f"Missing required argument: {required}")

    chords_raw = arguments["chords"]
    if not isinstance(chords_raw, list) or not chords_raw:
        raise ValueError("chords must be a non-empty list")

    chord_specs: list[ChordSpec] = []
    for i, c in enumerate(chords_raw):
        if not isinstance(c, dict):
            raise ValueError(f"chords[{i}] must be an object")
        if "numeral" not in c or "duration_beats" not in c:
            raise ValueError(f"chords[{i}] requires 'numeral' and 'duration_beats'")
        chord_specs.append(ChordSpec(
            numeral=c["numeral"],
            duration_beats=float(c["duration_beats"]),
            inversion=c.get("inversion"),
            voicing=c.get("voicing", "close"),
        ))

    humanize_raw = arguments.get("humanize") or {}
    humanize = HumanizeSpec(
        velocity_range=int(humanize_raw.get("velocity_range", 0)),
        timing_ms=int(humanize_raw.get("timing_ms", 0)),
        base_velocity=int(humanize_raw.get("base_velocity", 80)),
    )

    return GenerationRequest(
        key_center=arguments["key_center"],
        scale_type=arguments["scale_type"],
        bpm=int(arguments["bpm"]),
        chords=chord_specs,
        octave=int(arguments.get("octave", 4)),
        time_signature=arguments.get("time_signature", "4/4"),
        humanize=humanize,
        seed=arguments.get("seed"),
        filename=arguments.get("filename"),
        prompt_context=arguments.get("prompt_context"),
        generation_notes=arguments.get("generation_notes"),
    )
```

Update the `call_tool` dispatcher to handle the new tool:

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info("tool call: %s args=%s", name, list(arguments.keys()))
    if name == "generate_midi_progression":
        result = handle_generate_midi_progression(arguments)
    elif name == "set_output_directory":
        result = handle_set_output_directory(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [TextContent(type="text", text=json.dumps(result, indent=2))]
```

- [ ] **Step 4: Run the test to verify it passes**

```
.venv/bin/python -m pytest tests/test_mcp_server.py::test_generate_minimal_args -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/banjo/mcp_server.py tests/test_mcp_server.py
git commit -m "Implement generate_midi_progression handler with minimal args"
```

---

## Task 7: `generate_midi_progression` handler — full args + error paths (TDD)

**Files:**
- Modify: `tests/test_mcp_server.py`

The handler from Task 6 already supports all 11 fields; this task locks behavior in with regression tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_server.py`:

```python
def test_generate_full_args(isolated_config_dir, tmp_path):
    """All 11 fields exercised, with humanization, secondary dominant, alterations."""
    out = tmp_path / "out"
    config.set_output_directory(out)

    result = mcp_server.handle_generate_midi_progression({
        "key_center": "Eb",
        "scale_type": "major",
        "bpm": 72,
        "chords": [
            {"numeral": "Imaj9", "duration_beats": 4, "voicing": "drop2"},
            {"numeral": "V7/vi", "duration_beats": 2, "voicing": "drop2"},
            {"numeral": "vi9",   "duration_beats": 4, "voicing": "drop2"},
            {"numeral": "ii9",   "duration_beats": 2, "voicing": "drop2"},
            {"numeral": "V13",   "duration_beats": 2, "voicing": "drop2"},
            {"numeral": "Imaj9", "duration_beats": 2, "voicing": "drop2", "inversion": 1},
        ],
        "octave": 4,
        "time_signature": "4/4",
        "humanize": {"velocity_range": 10, "timing_ms": 6, "base_velocity": 75},
        "seed": 7,
        "filename": "neo_soul_test",
        "prompt_context": "Neo-soul in Eb with secondary dominant approach to vi.",
        "generation_notes": "Drop-2 voicings throughout for a slightly horn-like spread.",
    })

    midi_path = Path(result["filepath"])
    assert midi_path.name == "neo_soul_test.mid"
    assert midi_path.exists()
    assert midi_path.parent == out.resolve()

    # Sidecar contains the prompt context and generation notes.
    sidecar_text = Path(result["sidecar_path"]).read_text()
    assert "Neo-soul in Eb" in sidecar_text
    assert "Drop-2 voicings" in sidecar_text
    assert "Seed: 7" in sidecar_text

    assert result["total_beats"] == 16
    assert len(result["resolved"]) == 6
    # Inversion override on the last chord made it through.
    assert result["resolved"][-1]["inversion"] == 1


def test_generate_missing_required_raises():
    with pytest.raises(ValueError, match="Missing required argument: key_center"):
        mcp_server.handle_generate_midi_progression({
            "scale_type": "major", "bpm": 100, "chords": [{"numeral": "I", "duration_beats": 4}],
        })


def test_generate_empty_chords_raises():
    with pytest.raises(ValueError, match="non-empty list"):
        mcp_server.handle_generate_midi_progression({
            "key_center": "C", "scale_type": "major", "bpm": 100, "chords": [],
        })


def test_generate_chord_missing_fields_raises():
    with pytest.raises(ValueError, match="numeral.*duration_beats"):
        mcp_server.handle_generate_midi_progression({
            "key_center": "C", "scale_type": "major", "bpm": 100,
            "chords": [{"numeral": "I"}],  # missing duration_beats
        })


def test_generate_bad_numeral_raises():
    """Parser errors propagate cleanly to MCP."""
    with pytest.raises(ValueError):  # parse_roman_numeral raises ValueError
        mcp_server.handle_generate_midi_progression({
            "key_center": "C", "scale_type": "major", "bpm": 100,
            "chords": [{"numeral": "ZZZZ", "duration_beats": 4}],
        })


def test_generate_bad_scale_raises():
    with pytest.raises(ValueError, match="Unknown mode"):
        mcp_server.handle_generate_midi_progression({
            "key_center": "C", "scale_type": "bogolian", "bpm": 100,
            "chords": [{"numeral": "I", "duration_beats": 4}],
        })


def test_generate_creates_default_output_dir(isolated_config_dir, tmp_path, monkeypatch):
    """When no config is set, falls back to DEFAULT_OUTPUT_DIR (created on first write)."""
    # isolated_config_dir fixture already redirects DEFAULT_OUTPUT_DIR into tmp_path.
    default_out = tmp_path / "Music" / "banjo"
    assert not default_out.exists()

    result = mcp_server.handle_generate_midi_progression({
        "key_center": "G", "scale_type": "major", "bpm": 90,
        "chords": [{"numeral": "I", "duration_beats": 4}],
    })

    assert default_out.is_dir()
    assert Path(result["filepath"]).parent == default_out.resolve()
```

- [ ] **Step 2: Run the tests**

```
.venv/bin/python -m pytest tests/test_mcp_server.py -v
```

Expected: all pass (handler logic from Task 6 already supports these).

If any fail because the handler is missing a code path (e.g. the parser raises something other than `ValueError`), patch the handler accordingly — keep ValueError as the public error type.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_server.py
git commit -m "Lock in generate_midi_progression behavior with full + error tests"
```

---

## Task 8: End-to-end smoke test of MCP dispatcher

**Files:**
- Modify: `tests/test_mcp_server.py`

So far we've tested handlers directly. Add one test that exercises the `@server.call_tool` async dispatcher to confirm wiring is correct.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_server.py`:

```python
import asyncio


def test_call_tool_dispatcher_generate(isolated_config_dir, tmp_path):
    """The async call_tool dispatcher returns TextContent with JSON-encoded result."""
    config.set_output_directory(tmp_path / "out")

    response = asyncio.run(mcp_server.call_tool("generate_midi_progression", {
        "key_center": "C", "scale_type": "major", "bpm": 100,
        "chords": [{"numeral": "I", "duration_beats": 4}],
    }))

    assert len(response) == 1
    assert response[0].type == "text"
    payload = json.loads(response[0].text)
    assert payload["total_beats"] == 4
    assert "filepath" in payload


def test_call_tool_dispatcher_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        asyncio.run(mcp_server.call_tool("nonexistent", {}))


def test_list_tools_returns_two_tools():
    tools = asyncio.run(mcp_server.list_tools())
    names = {t.name for t in tools}
    assert names == {"generate_midi_progression", "set_output_directory"}
    # Schemas are non-trivial.
    schemas = {t.name: t.inputSchema for t in tools}
    assert schemas["generate_midi_progression"]["required"] == [
        "key_center", "scale_type", "bpm", "chords",
    ]
```

Note: `mcp_server.call_tool` and `mcp_server.list_tools` are bound coroutines created by the `@server.call_tool()` and `@server.list_tools()` decorators. Depending on the MCP SDK version, they may be exposed as module-level names or only registered with the server. If the test fails with `AttributeError`, refactor `call_tool` and `list_tools` to be plain async functions defined at module level, then registered with the server explicitly:

```python
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    ...

server.call_tool()(call_tool)  # register after defining
```

Same for `list_tools`. This keeps them callable from tests.

- [ ] **Step 2: Run the test**

```
.venv/bin/python -m pytest tests/test_mcp_server.py -v
```

Expected: all pass. If the dispatcher tests fail per the note above, refactor and re-run.

- [ ] **Step 3: Commit**

```bash
git add src/banjo/mcp_server.py tests/test_mcp_server.py
git commit -m "Add MCP dispatcher smoke tests"
```

---

## Task 9: README — Phase 2 setup

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the "Phase 2 (next)" section with a real Phase 2 section**

In `README.md`, replace the `## Phase 2 (next)` section at the bottom with:

````markdown
## Phase 2: MCP server

`banjo-mcp` is a stdio-transport MCP server that exposes the generator to any
MCP host (Claude Desktop, Continue, etc).

### Tools

- **`generate_midi_progression`** — render a Roman numeral progression to MIDI.
  Required: `key_center`, `scale_type`, `bpm`, `chords`. Optional: `octave`,
  `time_signature`, `humanize`, `seed`, `filename`, `prompt_context`,
  `generation_notes`. Returns `{filepath, sidecar_path, resolved, total_beats}`.

- **`set_output_directory`** — persist the output directory to
  `~/.banjo/config.json`. Default is `~/Music/banjo/`, created on first write.

### Claude Desktop config

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "banjo": {
      "command": "/Users/david/Github/banjo/.venv/bin/banjo-mcp"
    }
  }
}
```

Restart Claude Desktop. The two tools should appear in the tools picker.

### Logs

Server logs go to stderr at `INFO` level. To inspect them while developing:

```bash
.venv/bin/banjo-mcp 2> /tmp/banjo-mcp.log
# (in another shell) tail -f /tmp/banjo-mcp.log
```

### After schema changes

Claude Desktop caches tool schemas at startup. If you add a tool, change a
field, or rename anything in `inputSchema`, **fully quit and relaunch
Claude Desktop** (Cmd+Q, not just close window). Refreshing or starting a
new chat does not reload tool definitions.

### Output directory

Files land in `~/Music/banjo/` by default. Change it from inside Claude Desktop:

> "Set the banjo output directory to /Users/david/Music/Ableton/banjo-clips"

That call writes the path to `~/.banjo/config.json` and persists across
restarts.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document Phase 2 MCP server in README"
```

---

## Final verification

After all tasks:

```bash
.venv/bin/python -m pytest -v
```

Expected: 54 (Phase 1) + 5 (config) + ~12 (mcp_server) = ~71 passed.

Then validate live with Claude Desktop:
1. Edit `claude_desktop_config.json` per Task 9.
2. Fully quit Claude Desktop (Cmd+Q) and relaunch.
3. Ask: "Generate a I-vi-IV-V in C major at 100 BPM."
4. Confirm a `.mid` lands in `~/Music/banjo/` and appears in the conversation.

---

## Future improvements (out of scope for v1)

These are deferred unless real-world usage proves them necessary:

- **Pydantic for argument validation.** `pydantic` is already a transitive
  dep via `mcp`, so swapping the manual validation in
  `_build_generation_request` for a `BaseModel` is a mechanical refactor.
  Worth doing once the tool surface grows or LLMs are observed sending
  malformed payloads we don't catch cleanly. The hand-written JSON schema
  stays regardless — Claude needs the per-field `description` strings.
- **Wrap `generate()` in `asyncio.to_thread()`.** Single-progression render
  is a few milliseconds, so the sync call is fine. If we add corpus-scale
  batch generation or analysis tools that block the event loop, switch then.
- **`list_voicings` tool.** The 6 voicings are already in the JSON schema
  enum for the `voicing` field, so the LLM sees them at tool-discovery
  time without an extra round-trip. Add only if we discover the model
  forgetting them in long conversations.
