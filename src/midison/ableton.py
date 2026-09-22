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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pythonosc import osc_message_builder, udp_client
from pythonosc.osc_message import OscMessage

from midison.events import ResolvedProgression, TimedNote, resolve_progression_notes
from midison.midi_writer import GenerationRequest

logger = logging.getLogger("midison.ableton")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_SEND_PORT = 11000      # AbletonOSC listens here
DEFAULT_RECEIVE_PORT = 11001   # AbletonOSC replies here


@dataclass
class AbletonSessionState:
    """Snapshot of the active Ableton Live session state."""

    tempo: float = 120.0
    signature_numerator: int = 4
    signature_denominator: int = 4
    selected_track: int = 0
    selected_scene: int = 0
    root_note: int | None = None
    scale_name: str | None = None
    connected: bool = False

    @property
    def time_signature(self) -> str:
        """Formatted time signature string, e.g. '4/4'."""
        return f"{self.signature_numerator}/{self.signature_denominator}"

    @property
    def key_name(self) -> str | None:
        """Name of root note (0=C .. 11=B) if set in session."""
        if self.root_note is None:
            return None
        pitch_names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
        if 0 <= self.root_note < 12:
            return pitch_names[self.root_note]
        return None


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

    def _create_receive_socket(self, timeout: float) -> socket.socket | None:
        """Create and bind a UDP socket on receive_port with reuse options."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass

        sock.settimeout(timeout)
        try:
            sock.bind((self.host, self.receive_port))
            return sock
        except OSError as exc:
            logger.debug("Failed binding AbletonOSC receive socket on %d: %s", self.receive_port, exc)
            sock.close()
            return None

    def query(self, address: str, *args: Any, timeout: float = 0.3) -> list[Any] | None:
        """Send an OSC query and await a single parsed response on receive_port."""
        sock = self._create_receive_socket(timeout)
        if sock is None:
            return None

        try:
            self.send(address, *args)
            data, _ = sock.recvfrom(4096)
            msg = OscMessage(data)
            return list(msg.params)
        except (socket.timeout, TimeoutError):
            return None
        except Exception as exc:
            logger.debug("Error during OSC query '%s': %s", address, exc)
            return None
        finally:
            sock.close()

    def query_session_state(self, timeout: float = 0.3) -> AbletonSessionState:
        """
        Query active Ableton Live session for tempo, time signature,
        currently selected track & clip slot (scene), and scale/key.
        """
        state = AbletonSessionState()
        sock = self._create_receive_socket(timeout)
        if sock is None:
            return state

        queries = [
            "/live/song/get/tempo",
            "/live/song/get/signature_numerator",
            "/live/song/get/signature_denominator",
            "/live/view/get/selected_track",
            "/live/view/get/selected_scene",
            "/live/song/get/root_note",
            "/live/song/get/scale_name",
        ]

        try:
            for q in queries:
                self.send(q)

            end_time = time.monotonic() + timeout
            received_any = False

            while True:
                remaining = end_time - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(max(0.01, remaining))
                try:
                    data, _ = sock.recvfrom(4096)
                    msg = OscMessage(data)
                    addr = msg.address
                    params = msg.params
                    received_any = True

                    if addr == "/live/song/get/tempo" and params:
                        state.tempo = float(params[0])
                    elif addr == "/live/song/get/signature_numerator" and params:
                        state.signature_numerator = int(params[0])
                    elif addr == "/live/song/get/signature_denominator" and params:
                        state.signature_denominator = int(params[0])
                    elif addr == "/live/view/get/selected_track" and params:
                        state.selected_track = int(params[0])
                    elif addr == "/live/view/get/selected_scene" and params:
                        state.selected_scene = int(params[0])
                    elif addr == "/live/song/get/root_note" and params and params[0] is not None:
                        state.root_note = int(params[0])
                    elif addr == "/live/song/get/scale_name" and params and params[0] is not None:
                        state.scale_name = str(params[0])
                except (socket.timeout, TimeoutError):
                    break
                except Exception as exc:
                    logger.debug("Error reading OSC response packet: %s", exc)

            if received_any:
                state.connected = True

        except Exception as exc:
            logger.debug("Error querying Ableton session state: %s", exc)
        finally:
            sock.close()

        return state

    def is_connected(self, timeout: float = 0.3) -> bool:
        """Check if Ableton Live is running and responding to OSC."""
        return self.query_session_state(timeout=timeout).connected

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
        track_index: int | None = None,
        clip_index: int | None = None,
        fire: bool = True,
        sync_session: bool = True,
    ) -> dict[str, Any]:
        """
        Resolve a chord progression and inject it directly into an Ableton Live clip slot.
        If track_index or clip_index is None, automatically queries the active Ableton
        session to inject into the currently selected track and clip slot.
        """
        session_synced = False
        target_track = track_index
        target_clip = clip_index

        if (target_track is None or target_clip is None) and sync_session:
            state = self.query_session_state()
            if state.connected:
                session_synced = True
                if target_track is None:
                    target_track = state.selected_track
                if target_clip is None:
                    target_clip = state.selected_scene

        if target_track is None:
            target_track = 0
        if target_clip is None:
            target_clip = 0

        resolved = resolve_progression_notes(request)

        # 1. Create clip with the exact duration of the progression
        self.create_clip(target_track, target_clip, resolved.total_beats)

        # 2. Add all voice-led and grooved notes
        self.add_notes(target_track, target_clip, resolved.notes)

        # 3. Optionally launch/fire the clip
        if fire:
            self.fire_clip(target_track, target_clip)

        return {
            "status": "success",
            "track_index": target_track,
            "clip_index": target_clip,
            "total_beats": resolved.total_beats,
            "notes_count": len(resolved.notes),
            "chords": [m["numeral"] for m in resolved.resolved_metadata],
            "fired": fire,
            "session_synced": session_synced,
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
