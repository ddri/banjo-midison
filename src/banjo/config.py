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
