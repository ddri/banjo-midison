# banjo

MIDI chord progression generator from Roman numeral analysis. Named after Banjo Paterson.

Phase 1: theory layer + test corpus. No MCP server yet — this phase exists to validate that the music theory engine produces musically correct output before any LLM plumbing is added.

## Setup

```bash
cd /Users/david/Github/banjo
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Run the test suite

```bash
pytest
```

54 tests covering the parser, chord builder, voicings, and MIDI writer.

## Generate the audition corpus

```bash
banjo-corpus
# or: python -m banjo.corpus
```

Writes 12 `.mid` files plus `.md` sidecars to `./output/` by default. Drag them into Ableton and audition each one. If anything sounds wrong, the bug is in the theory layer — fix it here before moving to Phase 2.

Override the output directory:

```bash
banjo-corpus --output-dir ~/Music/banjo-test
```

## Corpus contents

| # | File | What it tests |
|---|------|---------------|
| 01 | ii-V-I in C major, close voicings | Sanity check |
| 02 | Neo-soul progression in F, rootless | Extensions, rootless voicings |
| 03 | Neo-soul in Eb with V7/vi | Secondary dominants, drop-2 |
| 04 | I-bVII-IV-I in G | Modal mixture (mixolydian borrow) |
| 05 | D dorian i9-IV9 vamp | Modal harmony |
| 06 | A minor with V7/iv | Secondary dominant in minor |
| 07 | ii-V7b9-I in C | Altered dominant |
| 08 | Spread voicing test in C | Voicing transformation |
| 09 | E mixolydian funk | Modal + extensions |
| 10 | Dm7 - Em7b5 - A7b9 - Dm7 | Half-diminished |
| 11 | Drop-2-and-4 in Bb | Voicing transformation |
| 12 | C - Eb - Ab - Db chromatic | Heavy modal mixture |

## Architecture

```
src/banjo/
├── theory.py        # Roman numeral parser, scales, chord builder
├── voicings.py      # close, drop2, drop3, drop2and4, spread, rootless
├── midi_writer.py   # mido wrapper, sidecar generation
└── corpus.py        # test corpus CLI
```

## Roman numeral grammar (v1)

Supported:

- Triad qualities by case: `I` (major), `i` (minor), `vii°` or `viio` (diminished), `III+` (augmented)
- Sevenths and extensions: `7`, `maj7`, `9`, `11`, `13`, `maj9`, `maj13`
- Alterations: `b5`, `#5`, `b9`, `#9`, `#11`, `b13`
- Modal mixture / chromatic roots: `bVII`, `bIII`, `bVI`, `bII`, `#IV`
- Secondary dominants and applied chords: `V/vi`, `V7/ii`, `vii°/V`
- Half-diminished: `iiø` (treated as diminished triad + minor 7)
- Inversions via figured-bass shorthand: `V6` (first), `V64` (second), `V42` (third of seventh chord)
- Inversions also settable explicitly via `ChordSpec.inversion`

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
