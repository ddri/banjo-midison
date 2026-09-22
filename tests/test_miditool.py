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
