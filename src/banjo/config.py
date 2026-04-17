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
