"""
Direct Ableton Live integration for Banjo via AbletonOSC.

Allows Claude Desktop and the Banjo CLI to directly create and populate
MIDI clips on specific tracks and clip slots in an active Ableton Live session.
Zero manual file export or drag-and-drop required.
"""

from __future__ import annotations

import logging
import socket
import subprocess
from pathlib import Path
from typing import Any

from pythonosc import osc_message_builder, udp_client

from midison.events import ResolvedProgression, TimedNote, resolve_progression_notes
from midison.midi_writer import GenerationRequest

logger = logging.getLogger("midison.ableton")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_SEND_PORT = 11000      # AbletonOSC listens here
DEFAULT_RECEIVE_PORT = 11001   # AbletonOSC replies here


class AbletonClient:
    """Client for controlling Ableton Live via the AbletonOSC Remote Script."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        send_port: int = DEFAULT_SEND_PORT,
        receive_port: int = DEFAULT_RECEIVE_PORT,
    ) -> None:
        self.host = host
        self.send_port = send_port
        self.receive_port = receive_port
        self.client = udp_client.SimpleUDPClient(host, send_port)

    def send(self, address: str, *args: Any) -> None:
        """Send an OSC message to Ableton Live."""
        self.client.send_message(address, list(args))

    def query(self, address: str, *args: Any, timeout: float = 0.5) -> list[Any] | None:
        """Send an OSC message and await a single response on receive_port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.bind((self.host, self.receive_port))
        except OSError:
            # Port might be in use by another listener; attempt non-blocking query
            try:
                self.send(address, *args)
            except Exception as exc:
                logger.debug(f"Failed sending OSC query: {exc}")
            return None

        try:
            self.send(address, *args)
            data, _ = sock.recvfrom(4096)
            # Parse OSC response if needed, or return raw acknowledgment
            return [data]
        except (socket.timeout, TimeoutError):
            return None
        finally:
            sock.close()

    def is_connected(self, timeout: float = 0.3) -> bool:
        """Check if Ableton Live is running and responding to OSC."""
        # Simple test ping
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            # Try connecting UDP socket to test route
            sock.connect((self.host, self.send_port))
            # Send test message
            self.send("/live/test")
            return True
        except Exception:
            return False
        finally:
            sock.close()

    def create_clip(self, track_index: int, clip_index: int, length_beats: float) -> None:
        """Create a new empty MIDI clip in the specified track and slot."""
        self.send("/live/clip_slot/create_clip", track_index, clip_index, float(length_beats))

    def add_note(
        self,
        track_index: int,
        clip_index: int,
        pitch: int,
        start_time: float,
        duration: float,
        velocity: int,
        mute: bool = False,
    ) -> None:
        """Add a single note to an existing clip."""
        self.send(
            "/live/clip/add/notes",
            track_index,
            clip_index,
            int(pitch),
            float(start_time),
            float(duration),
            int(velocity),
            int(mute),
        )

    def add_notes(
        self,
        track_index: int,
        clip_index: int,
        notes: list[TimedNote],
    ) -> None:
        """Add multiple timed notes to a clip."""
        for n in notes:
            self.add_note(
                track_index=track_index,
                clip_index=clip_index,
                pitch=n.pitch,
                start_time=n.start_beat,
                duration=n.duration_beats,
                velocity=n.velocity,
                mute=False,
            )

    def fire_clip(self, track_index: int, clip_index: int) -> None:
        """Start playback of the clip."""
        self.send("/live/clip/fire", track_index, clip_index)

    def stop_clip(self, track_index: int, clip_index: int) -> None:
        """Stop playback of the clip."""
        self.send("/live/clip/stop", track_index, clip_index)

    def inject_progression(
        self,
        request: GenerationRequest,
        track_index: int = 0,
        clip_index: int = 0,
        fire: bool = True,
    ) -> dict[str, Any]:
        """
        Resolve a chord progression and inject it directly into an Ableton Live clip slot.
        """
        resolved = resolve_progression_notes(request)

        # 1. Create clip with the exact duration of the progression
        self.create_clip(track_index, clip_index, resolved.total_beats)

        # 2. Add all voice-led and grooved notes
        self.add_notes(track_index, clip_index, resolved.notes)

        # 3. Optionally launch/fire the clip
        if fire:
            self.fire_clip(track_index, clip_index)

        return {
            "status": "success",
            "track_index": track_index,
            "clip_index": clip_index,
            "total_beats": resolved.total_beats,
            "notes_count": len(resolved.notes),
            "chords": [m["numeral"] for m in resolved.resolved_metadata],
            "fired": fire,
        }


def find_ableton_remote_scripts_dir() -> Path:
    """Find the best user directory for Ableton MIDI Remote Scripts on this machine."""
    # Official Ableton location (shared across all versions):
    user_lib_scripts = Path.home() / "Music/Ableton/User Library/Remote Scripts"
    user_lib_scripts.mkdir(parents=True, exist_ok=True)
    return user_lib_scripts


def install_ableton_osc(target_dir: Path | None = None) -> Path:
    """
    Install the AbletonOSC Remote Script into Ableton Live's Remote Scripts directory.
    Uses git clone or updates existing repository.
    """
    if target_dir is None:
        parent_dir = find_ableton_remote_scripts_dir()
        if parent_dir is None:
            raise RuntimeError("Could not locate Ableton Remote Scripts directory.")
        target_dir = parent_dir / "AbletonOSC"
    else:
        target_dir = Path(target_dir)

    target_dir.parent.mkdir(parents=True, exist_ok=True)

    if target_dir.exists() and (target_dir / ".git").exists():
        # Update existing
        subprocess.run(["git", "-C", str(target_dir), "pull"], check=True, capture_output=True)
    elif target_dir.exists():
        # Directory exists already
        pass
    else:
        # Clone fresh
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/ideoforms/AbletonOSC.git", str(target_dir)],
            check=True,
            capture_output=True,
        )

    # Also make sure it's accessible from Preferences User Remote Scripts if User Library was targeted
    pref_base = Path.home() / "Library/Preferences/Ableton"
    if pref_base.exists():
        for d in sorted(pref_base.glob("Live 12*"), reverse=True):
            user_scripts = d / "User Remote Scripts"
            if user_scripts.exists():
                pref_dest = user_scripts / "AbletonOSC"
                if not pref_dest.exists():
                    try:
                        pref_dest.symlink_to(target_dir)
                    except OSError:
                        pass

    return target_dir
