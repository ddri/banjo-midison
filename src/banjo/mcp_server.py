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
from banjo.midi_writer import (
    ChordSpec,
    GenerationRequest,
    HumanizeSpec,
    generate,
)
from banjo.theory import MODE_INTERVALS, parse_pitch_class

logger = logging.getLogger("banjo.mcp")

server: Server = Server("banjo")


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

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

    try:
        parse_pitch_class(arguments["key_center"])
    except ValueError:
        raise ValueError(f"Invalid key_center: {arguments['key_center']!r}")

    if arguments["scale_type"] not in MODE_INTERVALS:
        raise ValueError(
            f"Invalid scale_type: {arguments['scale_type']!r}. "
            f"Valid options: {sorted(MODE_INTERVALS.keys())}"
        )

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


# ---------------------------------------------------------------------------
# MCP dispatcher
# ---------------------------------------------------------------------------

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
