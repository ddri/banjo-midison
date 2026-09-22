"""
MCP server wrapping midison's MIDI generator.

Transport: stdio (for use from Claude Desktop or any MCP host).

Exposes:
  - generate_midi_progression: render a Roman numeral progression to MIDI.
  - set_output_directory: persist the output directory to ~/.midison/config.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from midison import config
from midison.grooves import list_grooves
from midison.midi_writer import (
    ChordSpec,
    GenerationRequest,
    HumanizeSpec,
    generate,
)
from midison.theory import MODE_INTERVALS, parse_pitch_class
from midison.stream import stream_progression
from midison.ableton import AbletonClient, install_ableton_osc
from midison.miditool import install_m4l_device

logger = logging.getLogger("midison.mcp")

server: Server = Server("midison")


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
                    "pattern": {
                        "type": "string",
                        "enum": sorted(list_grooves()),
                        "default": "block",
                        "description": (
                            "Rhythmic playback pattern / comping groove for the chord notes. "
                            "'block' — all notes hit simultaneously and hold for full duration. "
                            "'strum' — notes onset with a slight staggered delay from bottom to top. "
                            "'arpeggio_up' / 'arpeggio_down' — sequential ascending / descending notes. "
                            "'charleston' — classic dotted-quarter (beat 1) + eighth stab (and-of-2) (Jazz, Neo-soul, House). "
                            "'four_on_floor' — quarter-note pulses with alternating accents (Indie rock, House piano). "
                            "'bossa' — Brazilian Bossa Nova syncopation with bass and offbeat stabs. "
                            "'tresillo' — 3+3+2 syncopation (Afrobeats, Latin, Pop). "
                            "'reggae_skank' — upbeat offbeat chops on the 'and' of the beat. "
                            "'waltz' — 3/4 meter groove: bass on 1, chord chops on 2 & 3. "
                            "'comp_syncopated' — syncopated pulses on beats 0.0, 1.5, 3.0."
                        ),
                    },
                },
            },
        },
        "octave": {
            "type": "integer",
            "minimum": 0,
            "maximum": 9,
            "default": 3,
            "description": (
                "Root octave in the theory engine's numbering: octave 4 = Ableton C3 "
                "(MIDI 60, middle C). Default 3 places the root one octave below middle C — "
                "a comfortable comping register below melody range. "
                "For most songwriting, stay between 2 and 4. "
                "Above 5 puts chords in melody territory."
            ),
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
                "Persisted to ~/.midison/config.json across server restarts."
            ),
        },
    },
    "required": ["path"],
}

GET_ABLETON_SESSION_STATE_SCHEMA = {
    "type": "object",
    "properties": {
        "timeout": {
            "type": "number",
            "default": 0.3,
            "description": "Timeout in seconds to wait for Ableton Live OSC response (default: 0.3).",
        },
    },
}

SEND_TO_ABLETON_SCHEMA = {
    "type": "object",
    "required": ["key_center", "scale_type", "chords"],
    "properties": {
        **GENERATE_MIDI_PROGRESSION_SCHEMA["properties"],
        "track_index": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Ableton Live track index (0-indexed). Defaults to currently selected track "
                "in Live if session sync is active, or 0."
            ),
        },
        "clip_index": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Ableton Live clip slot index (0-indexed). Defaults to currently selected clip slot "
                "in Live if session sync is active, or 0."
            ),
        },
        "fire": {
            "type": "boolean",
            "default": True,
            "description": "Whether to immediately launch/play the clip in Ableton after injecting.",
        },
        "auto_sync": {
            "type": "boolean",
            "default": True,
            "description": (
                "When true, automatically synchronizes tempo, time signature, track, and clip slot "
                "from the active Ableton Live session when those parameters are omitted."
            ),
        },
    },
}

STREAM_TO_MIDI_PORT_SCHEMA = {
    "type": "object",
    "required": ["key_center", "scale_type", "bpm", "chords"],
    "properties": {
        **GENERATE_MIDI_PROGRESSION_SCHEMA["properties"],
        "port_name": {
            "type": "string",
            "default": "Midison",
            "description": "Name of the macOS virtual or hardware MIDI output port (defaults to 'Midison').",
        },
        "loop": {
            "type": "boolean",
            "default": False,
            "description": "Whether to loop playback continuously.",
        },
    },
}

INSTALL_ABLETON_INTEGRATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "install_ableton_osc": {
            "type": "boolean",
            "default": True,
            "description": "Install AbletonOSC Remote Script for direct zero-drag clip injection.",
        },
        "install_max_generator": {
            "type": "boolean",
            "default": True,
            "description": "Install Midison Generator.amxd into Live 12 MIDI Tools / Max Generators.",
        },
    },
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
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
        Tool(
            name="get_ableton_session_state",
            description=(
                "Query active Ableton Live session state via AbletonOSC. Returns connection status, "
                "current tempo (BPM), time signature, active/selected track index, active/selected "
                "clip slot (scene) index, and session key/scale if configured in Live."
            ),
            inputSchema=GET_ABLETON_SESSION_STATE_SCHEMA,
        ),
        Tool(
            name="send_to_ableton",
            description=(
                "Directly inject a MIDI chord progression and groove into an active Ableton Live "
                "track and clip slot using AbletonOSC. Eliminates manual file exports and drag-and-drop. "
                "Automatically synchronizes with the active session tempo and currently selected track/slot "
                "when omitted. Creates the clip, writes all voice-led notes, and optionally triggers playback."
            ),
            inputSchema=SEND_TO_ABLETON_SCHEMA,
        ),
        Tool(
            name="stream_to_midi_port",
            description=(
                "Stream notes in real-time to a macOS CoreMIDI virtual port ('Midison') or hardware port. "
                "Allows auditioning progressions through an armed Ableton Live VST track live with zero latency."
            ),
            inputSchema=STREAM_TO_MIDI_PORT_SCHEMA,
        ),
        Tool(
            name="install_ableton_integrations",
            description=(
                "Automatically install AbletonOSC and the Live 12 Max Generator device "
                "into Ableton Live's User Library and Remote Scripts folders."
            ),
            inputSchema=INSTALL_ABLETON_INTEGRATIONS_SCHEMA,
        ),
        Tool(
            name="set_output_directory",
            description=(
                "Set the directory where generated MIDI files are written. "
                "The setting is persisted to ~/.midison/config.json across "
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

        voicing = c.get("voicing", "close")
        # Migration guard: rootless was removed from the voicing enum.
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

        pattern = c.get("pattern", "block")
        valid_patterns = set(list_grooves())
        if pattern not in valid_patterns:
            raise ValueError(
                f"chords[{i}]: Invalid pattern: {pattern!r}. Valid options: {sorted(valid_patterns)}"
            )

        chord_specs.append(ChordSpec(
            numeral=c["numeral"],
            duration_beats=float(c["duration_beats"]),
            inversion=c.get("inversion"),
            voicing=voicing,
            rootless=rootless,
            pattern=pattern,
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


def handle_get_ableton_session_state(arguments: dict) -> dict:
    """Query live session state and return structured context."""
    timeout = float(arguments.get("timeout", 0.3))
    client = AbletonClient()
    state = client.query_session_state(timeout=timeout)
    return {
        "connected": state.connected,
        "tempo": state.tempo,
        "time_signature": state.time_signature,
        "signature_numerator": state.signature_numerator,
        "signature_denominator": state.signature_denominator,
        "selected_track": state.selected_track,
        "selected_scene": state.selected_scene,
        "root_note": state.root_note,
        "scale_name": state.scale_name,
        "key_name": state.key_name,
    }


def handle_send_to_ableton(arguments: dict) -> dict:
    """Inject a progression directly into Ableton Live via AbletonOSC."""
    client = AbletonClient()
    auto_sync = bool(arguments.get("auto_sync", True))
    session_synced = False
    session_state = None

    if auto_sync and (
        "bpm" not in arguments
        or arguments.get("bpm") is None
        or "track_index" not in arguments
        or arguments.get("track_index") is None
        or "clip_index" not in arguments
        or arguments.get("clip_index") is None
    ):
        session_state = client.query_session_state()
        if getattr(session_state, "connected", False) is True:
            session_synced = True
            if "bpm" not in arguments or arguments["bpm"] is None:
                arguments["bpm"] = int(round(session_state.tempo))
            if "time_signature" not in arguments or arguments["time_signature"] is None:
                arguments["time_signature"] = session_state.time_signature
            if "track_index" not in arguments or arguments["track_index"] is None:
                arguments["track_index"] = session_state.selected_track
            if "clip_index" not in arguments or arguments["clip_index"] is None:
                arguments["clip_index"] = session_state.selected_scene

    # Defaults if still unassigned
    if "bpm" not in arguments or arguments["bpm"] is None:
        arguments["bpm"] = 120
    track_index = int(arguments.get("track_index", 0))
    clip_index = int(arguments.get("clip_index", 0))
    fire = bool(arguments.get("fire", True))

    request = _build_generation_request(arguments)

    result = client.inject_progression(
        request, track_index=track_index, clip_index=clip_index, fire=fire, sync_session=False
    )
    result["session_synced"] = session_synced
    if session_state and getattr(session_state, "connected", False) is True:
        result["session_tempo"] = session_state.tempo
        result["session_time_signature"] = session_state.time_signature

    # Also generate the file to disk so user has the sidecar/backup
    output_dir = config.get_output_directory()
    gen_result = generate(request, output_dir)
    result["file_path"] = str(gen_result.filepath)
    result["sidecar_path"] = str(gen_result.sidecar_path)
    return result


def handle_stream_to_midi_port(arguments: dict) -> dict:
    """Stream notes in real-time to a macOS virtual MIDI port or hardware port."""
    request = _build_generation_request(arguments)
    port_name = str(arguments.get("port_name", "Midison"))
    loop = bool(arguments.get("loop", False))

    resolved = stream_progression(request, port_name=port_name, loop=loop)
    return {
        "status": "success",
        "port": port_name,
        "bpm": request.bpm,
        "notes_streamed": len(resolved.notes),
        "total_beats": resolved.total_beats,
        "chords": [m["numeral"] for m in resolved.resolved_metadata],
    }


def handle_install_ableton_integrations(arguments: dict) -> dict:
    """Install AbletonOSC and/or Midison Generator into Ableton user directories."""
    installed: dict[str, str] = {}
    if arguments.get("install_ableton_osc", True):
        osc_path = install_ableton_osc()
        installed["ableton_osc"] = str(osc_path)
    if arguments.get("install_max_generator", True):
        m4l_path = install_m4l_device()
        installed["max_generator"] = str(m4l_path)
    return {
        "status": "success",
        "installed_paths": installed,
        "instructions": (
            "1. In Ableton Live Settings > Link/Tempo/MIDI > Control Surface, select 'AbletonOSC'. "
            "2. In Live 12 Piano Roll, click 'Generators' tab to use 'Midison Generator'."
        ),
    }


# ---------------------------------------------------------------------------
# MCP dispatcher
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info("tool call: %s args=%s", name, list(arguments.keys()))
    if name == "generate_midi_progression":
        result = handle_generate_midi_progression(arguments)
    elif name == "get_ableton_session_state":
        result = handle_get_ableton_session_state(arguments)
    elif name == "set_output_directory":
        result = handle_set_output_directory(arguments)
    elif name == "send_to_ableton":
        result = handle_send_to_ableton(arguments)
    elif name == "stream_to_midi_port":
        result = handle_stream_to_midi_port(arguments)
    elif name == "install_ableton_integrations":
        result = handle_install_ableton_integrations(arguments)
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
