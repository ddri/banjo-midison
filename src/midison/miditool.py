"""
Ableton Live 12 Native MIDI Tool and Max for Live integration.

Generates native dictionaries for `live.miditool.out` and builds/installs
the `Midison Generator.amxd` MIDI Tool directly into Ableton Live 12's
`MIDI Tools/Max Generators` user library folder.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from midison.events import ResolvedProgression, TimedNote, resolve_progression_notes
from midison.midi_writer import GenerationRequest

logger = logging.getLogger("midison.miditool")


def to_miditool_dict(request: GenerationRequest) -> dict[str, Any]:
    """
    Convert a GenerationRequest into the dictionary structure expected
    by Ableton Live 12's `live.miditool.out`.
    """
    resolved = resolve_progression_notes(request)
    notes_payload = [
        {
            "pitch": int(n.pitch),
            "start_time": float(round(n.start_beat, 4)),
            "duration": float(round(n.duration_beats, 4)),
            "velocity": int(n.velocity),
            "mute": 0,
            "probability": 1.0,
        }
        for n in resolved.notes
    ]
    return {
        "notes": notes_payload,
        "metadata": {
            "key": request.key_center,
            "mode": request.scale_type,
            "total_beats": resolved.total_beats,
            "chords": [m["numeral"] for m in resolved.resolved_metadata],
        },
    }


def find_ableton_midi_tools_dir() -> Path:
    """Find the user library path for Ableton Live 12 MIDI Generators."""
    default_path = Path.home() / "Music/Ableton/User Library/MIDI Tools/Max Generators"
    default_path.mkdir(parents=True, exist_ok=True)
    return default_path


def create_amxd_container(patcher_json: dict[str, Any], device_type: str = "nagg") -> bytes:
    """
    Package a Max patcher dictionary into a valid Cycling '74 AMXD container file.
    device_type:
      'nagg': Live 12 MIDI Tool Generator
      'natt': Live 12 MIDI Tool Transformation
      'mmmm': MIDI Effect
    """
    json_str = json.dumps(patcher_json, indent="\t")
    json_bytes = json_str.encode("utf-8")

    # Header:
    # ampf (4) + len(type) (4) + type (4) + meta (4) + len(meta) (4) + meta_val (4) + ptch (4) + len(ptch) (4)
    header = (
        b"ampf\x04\x00\x00\x00"
        + device_type.encode("ascii")
        + b"meta\x04\x00\x00\x00\x00\x00\x00\x00"
        + b"ptch"
        + len(json_bytes).to_bytes(4, "little")
    )
    return header + json_bytes


def get_midison_generator_patcher() -> dict[str, Any]:
    """
    Generate the Max Patcher JSON definition for Midison Generator (Live 12 MIDI Tool).
    """
    js_code = """
autowatch = 1;
inlets = 1;
outlets = 1;

var rootNotes = {"C":0,"Db":1,"C#":1,"D":2,"Eb":3,"D#":3,"E":4,"F":5,"F#":6,"Gb":6,"G":7,"Ab":8,"G#":8,"A":9,"Bb":10,"A#":10,"B":11};
var scaleIntervals = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11]
};

var romanOffsets = {
    "i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6
};

function generate(progStr, keyStr, modeStr, voicingStr, grooveStr) {
    keyStr = keyStr || "C";
    modeStr = modeStr || "major";
    voicingStr = voicingStr || "drop2";
    grooveStr = grooveStr || "block";
    progStr = progStr || "ii7 - V7 - Imaj7";

    var rootPc = rootNotes[keyStr] || 0;
    var scale = scaleIntervals[modeStr] || scaleIntervals["major"];
    var tokens = progStr.split(/[-–—,\\s]+/).filter(function(s){ return s.length > 0; });
    
    var notes = [];
    var beatOffset = 0.0;
    var durationPerChord = 4.0;

    for (var i = 0; i < tokens.length; i++) {
        var tok = tokens[i].trim();
        var lower = tok.toLowerCase().replace(/[^a-z]/g, "");
        var scaleDeg = romanOffsets[lower] || 0;
        var chordRootPc = (rootPc + scale[scaleDeg % scale.length]) % 12;

        // Base 7th chord tones: 1, 3, 5, 7
        var chordNotes = [
            48 + chordRootPc,
            48 + ((rootPc + scale[(scaleDeg + 2) % scale.length]) % 12),
            48 + ((rootPc + scale[(scaleDeg + 4) % scale.length]) % 12),
            48 + ((rootPc + scale[(scaleDeg + 6) % scale.length]) % 12)
        ];
        
        // Ensure ascending pitch
        for (var n = 1; n < chordNotes.length; n++) {
            while (chordNotes[n] <= chordNotes[n - 1]) chordNotes[n] += 12;
        }

        // Apply Drop-2 voicing: second highest note dropped an octave
        if (voicingStr === "drop2" && chordNotes.length >= 4) {
            chordNotes[chordNotes.length - 2] -= 12;
            chordNotes.sort(function(a,b){ return a-b; });
        }

        // Apply Groove
        if (grooveStr === "charleston") {
            // Beat 1 (dur 1.0), Beat 2.5 (dur 0.5)
            for (var k = 0; k < chordNotes.length; k++) {
                notes.push({pitch: chordNotes[k], start_time: beatOffset + 0.0, duration: 1.0, velocity: 100});
                notes.push({pitch: chordNotes[k], start_time: beatOffset + 1.5, duration: 0.5, velocity: 85});
            }
        } else if (grooveStr === "bossa") {
            for (var k = 0; k < chordNotes.length; k++) {
                notes.push({pitch: chordNotes[k], start_time: beatOffset + 0.0, duration: 0.5, velocity: 100});
                notes.push({pitch: chordNotes[k], start_time: beatOffset + 1.5, duration: 0.5, velocity: 85});
                notes.push({pitch: chordNotes[k], start_time: beatOffset + 3.0, duration: 0.5, velocity: 90});
            }
        } else {
            // Block chord
            for (var k = 0; k < chordNotes.length; k++) {
                notes.push({pitch: chordNotes[k], start_time: beatOffset, duration: durationPerChord, velocity: 95});
            }
        }

        beatOffset += durationPerChord;
    }

    var dict = new Dict();
    dict.parse(JSON.stringify({notes: notes}));
    outlet(0, "dictionary", dict.name);
}

function dictionary(dictName) {
    // Triggered when Live passes input dict to generator
    generate("ii7 - V7 - Imaj7", "Eb", "major", "drop2", "charleston");
}
"""

    return {
        "patcher": {
            "fileversion": 1,
            "appversion": {
                "major": 9,
                "minor": 0,
                "revision": 0,
                "architecture": "x64",
                "modernui": 1,
            },
            "classnamespace": "box",
            "rect": [100.0, 100.0, 480.0, 380.0],
            "openinpresentation": 1,
            "default_fontsize": 12.0,
            "boxes": [
                {
                    "box": {
                        "id": "obj-1",
                        "maxclass": "newobj",
                        "text": "live.miditool.out",
                        "numinlets": 1,
                        "numoutlets": 0,
                        "patching_rect": [80.0, 300.0, 100.0, 22.0],
                    }
                },
                {
                    "box": {
                        "id": "obj-2",
                        "maxclass": "newobj",
                        "text": "live.miditool.in",
                        "numinlets": 1,
                        "numoutlets": 1,
                        "outlettype": [""],
                        "patching_rect": [80.0, 40.0, 95.0, 22.0],
                    }
                },
                {
                    "box": {
                        "id": "obj-js",
                        "maxclass": "newobj",
                        "text": "js",
                        "numinlets": 1,
                        "numoutlets": 1,
                        "outlettype": [""],
                        "patching_rect": [80.0, 160.0, 50.0, 22.0],
                        "saved_object_attributes": {
                            "code": js_code,
                        },
                    }
                },
                {
                    "box": {
                        "id": "obj-title",
                        "maxclass": "live.comment",
                        "text": "🎹 Midison Generator",
                        "presentation": 1,
                        "presentation_rect": [10.0, 10.0, 200.0, 20.0],
                    }
                },
                {
                    "box": {
                        "id": "obj-desc",
                        "maxclass": "live.comment",
                        "text": "Intelligent Voicings & Grooves",
                        "presentation": 1,
                        "presentation_rect": [10.0, 30.0, 200.0, 18.0],
                    }
                },
            ],
            "lines": [
                {
                    "patchline": {
                        "destination": ["obj-js", 0],
                        "source": ["obj-2", 0],
                    }
                },
                {
                    "patchline": {
                        "destination": ["obj-1", 0],
                        "source": ["obj-js", 0],
                    }
                },
            ],
        }
    }


def build_amxd_device(output_path: Path) -> Path:
    """Build the Midison Generator.amxd file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    patcher = get_midison_generator_patcher()
    amxd_bytes = create_amxd_container(patcher, device_type="nagg")
    output_path.write_bytes(amxd_bytes)
    return output_path


def install_m4l_device(target_dir: Path | None = None) -> Path:
    """
    Install Midison Generator.amxd into Ableton Live 12's user MIDI Tools folder.
    """
    if target_dir is None:
        target_dir = find_ableton_midi_tools_dir()
    else:
        target_dir = Path(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    device_path = target_dir / "Midison Generator.amxd"
    build_amxd_device(device_path)
    return device_path
