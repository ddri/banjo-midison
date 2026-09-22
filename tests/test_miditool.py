"""
Unit tests for Ableton Live 12 MIDI Tool and AMXD builder (banjo.miditool).
"""

from pathlib import Path

from midison.midi_writer import ChordSpec, GenerationRequest
from midison.miditool import (
    build_amxd_device,
    create_amxd_container,
    find_ableton_midi_tools_dir,
    get_midison_generator_patcher,
    install_m4l_device,
    to_miditool_dict,
)


def test_to_miditool_dict_structure():
    req = GenerationRequest(
        key_center="C",
        scale_type="major",
        bpm=120,
        chords=[
            ChordSpec(numeral="ii7", duration_beats=2.0, pattern="charleston"),
            ChordSpec(numeral="V7", duration_beats=2.0, pattern="block"),
        ],
    )
    res = to_miditool_dict(req)

    assert "notes" in res
    assert "metadata" in res
    assert res["metadata"]["key"] == "C"
    assert res["metadata"]["mode"] == "major"
    assert res["metadata"]["total_beats"] == 4.0
    assert len(res["notes"]) > 0

    first = res["notes"][0]
    assert "pitch" in first
    assert "start_time" in first
    assert "duration" in first
    assert "velocity" in first
    assert "mute" in first
    assert "probability" in first
    assert first["probability"] == 1.0


def test_create_amxd_container_header_and_format():
    sample_patcher = {"patcher": {"fileversion": 1, "boxes": [], "lines": []}}
    data = create_amxd_container(sample_patcher, device_type="nagg")

    assert data.startswith(b"ampf\x04\x00\x00\x00naggmeta")
    ptch_idx = data.find(b"ptch")
    assert ptch_idx != -1

    chunk_len = int.from_bytes(data[ptch_idx + 4 : ptch_idx + 8], "little")
    assert chunk_len > 0
    assert len(data) == ptch_idx + 8 + chunk_len


def test_build_amxd_device_writes_valid_file(tmp_path):
    dest = tmp_path / "Banjo Test.amxd"
    out = build_amxd_device(dest)

    assert out.exists()
    assert out.stat().st_size > 500
    with open(out, "rb") as f:
        head = f.read(16)
        assert head.startswith(b"ampf\x04\x00\x00\x00naggmeta")


def test_find_ableton_midi_tools_dir():
    p = find_ableton_midi_tools_dir()
    assert isinstance(p, Path)
    assert p.name == "Max Generators"


def test_install_m4l_device_in_custom_dir(tmp_path):
    dest_dir = tmp_path / "MIDI Tools" / "Max Generators"
    out_device = install_m4l_device(dest_dir)

    assert out_device.exists()
    assert out_device.name == "Midison Generator.amxd"
    assert out_device.stat().st_size > 500


def test_generator_patcher_presentation_and_controls():
    patcher_dict = get_midison_generator_patcher()
    p = patcher_dict["patcher"]

    assert p["openinpresentation"] == 1
    assert p["openrect"][2] == 152.0  # Standard Live 12 panel width

    box_ids = {b["box"]["id"]: b["box"] for b in p["boxes"]}

    # Core I/O and JS engine
    assert "obj-in" in box_ids
    assert box_ids["obj-in"]["text"] == "live.miditool.in"
    assert "obj-out" in box_ids
    assert box_ids["obj-out"]["text"] == "live.miditool.out"
    assert "obj-js" in box_ids
    assert "js midison_generator.js" in box_ids["obj-js"]["text"]

    # UI Controls
    assert "obj-menu-preset" in box_ids
    assert box_ids["obj-menu-preset"]["maxclass"] == "live.menu"
    assert "obj-menu-voicing" in box_ids
    assert box_ids["obj-menu-voicing"]["maxclass"] == "live.menu"
    assert "obj-menu-groove" in box_ids
    assert box_ids["obj-menu-groove"]["maxclass"] == "live.menu"
    assert "obj-num-oct" in box_ids
    assert box_ids["obj-num-oct"]["maxclass"] == "live.numbox"
    assert "obj-btn-human" in box_ids
    assert box_ids["obj-btn-human"]["maxclass"] == "live.text"
    assert "obj-btn-lead" in box_ids
    assert box_ids["obj-btn-lead"]["maxclass"] == "live.text"
    assert "obj-btn-rootless" in box_ids
    assert box_ids["obj-btn-rootless"]["maxclass"] == "live.text"
    assert "obj-btn-generate" in box_ids
    assert box_ids["obj-btn-generate"]["maxclass"] == "live.text"

    # Presentation rects on all interactive widgets
    interactive_ids = [
        "obj-menu-preset", "obj-menu-voicing", "obj-menu-groove",
        "obj-num-oct", "obj-btn-human", "obj-btn-lead", "obj-btn-rootless", "obj-btn-generate"
    ]
    for bid in interactive_ids:
        box = box_ids[bid]
        assert box.get("presentation") == 1
        assert "presentation_rect" in box

    # Verify lines
    lines = p["lines"]
    assert len(lines) >= 15
    dest_set = {line["patchline"]["destination"][0] for line in lines}
    assert "obj-js" in dest_set
    assert "obj-out" in dest_set


def test_generator_embedded_js_syntax():
    import subprocess
    from midison.miditool import MIDISON_GENERATOR_JS

    # Check key function names
    for fn in ["function generate", "function dictionary", "function preset", "function voicing", "function groove"]:
        assert fn in MIDISON_GENERATOR_JS

    # Validate JavaScript syntax with Node
    script = f"""
    // Mock Max Dict and outlet
    function Dict(name) {{
        this.name = name || "d1";
        this.contains = function() {{ return false; }};
        this.get = function() {{ return null; }};
        this.parse = function() {{}};
    }}
    function outlet(idx, type, val) {{}}

    {MIDISON_GENERATOR_JS}

    // Call handlers to verify no runtime syntax/reference errors
    preset(0);
    voicing("Drop 2");
    groove("Charleston");
    octave(3);
    voice_lead(1);
    rootless(0);
    humanize(1);
    generate();
    """
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node syntax validation failed: {res.stderr}"

