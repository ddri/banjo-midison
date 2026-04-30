# Banjo Midison

Banjo Midison is a MIDI chord composition tool for songwriters and producers. It allows you to chat with your choice of AI model about chord progressions and harmonic compositions, and have it generate MIDI files for you to use in your Digital Audio Workstation (DAW). 

It is not a DAW, nor is it a plugin. It is a standalone application that runs in the background and communicates with your MCP-compatible AI assistant via the Model Context Protocol (MCP). 

The idea is not to magically make cookie-cutter AI music, but to use AI as a collaborator to allow a songwriter to talk through chord ideas, progressions, and harmonic concepts with an AI assistant, and have it generate MIDI files (as well as a document of related concepts and chord charts) as part of the creative process.

## Setup

```bash
git clone https://github.com/ddri/banjo-midison.git
cd banjo-midison
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Run the test suite

```bash
pytest
```

107 tests covering the parser, chord builder, voicings, voice leading, MIDI writer, config, and MCP server.

## Generate the audition corpus

```bash
banjo-corpus
# or: python -m banjo.corpus
```

Writes 12 `.mid` files plus `.md` sidecars to `./output/` by default. Drag them into your DAW and audition each one to verify the theory engine.

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

## MCP server

`banjo-mcp` is a stdio-transport MCP server that exposes the generator to any
MCP host — Claude Desktop, Claude Code, Cursor, Continue, or anything else
that speaks the [Model Context Protocol](https://modelcontextprotocol.io).

### Tools

- **`generate_midi_progression`** — render a Roman numeral progression to MIDI.
  Required: `key_center`, `scale_type`, `bpm`, `chords`. Optional: `octave`,
  `time_signature`, `humanize`, `seed`, `voice_lead`, `filename`, `prompt_context`,
  `generation_notes`. Returns `{filepath, sidecar_path, resolved, total_beats}`.

- **`set_output_directory`** — persist the output directory to
  `~/.banjo/config.json`. Default is `~/Music/banjo/`, created on first write.

### Voice leading

When `voice_lead: true` is passed, each chord after the first has its inversion and octave register chosen to minimize voice motion from the previous chord. The per-chord `voicing` is preserved (drop2 stays drop2, etc.), and explicit inversions — whether via numeral form (`V64`) or the `inversion` field — are respected. Off by default; enabling it makes consecutive chords flow smoothly instead of jumping registers.

### Connecting to an MCP host

The server runs over stdio. Point your MCP host at the `banjo-mcp` entry
point. The exact config depends on your host:

**Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "banjo-midison": {
      "command": "/absolute/path/to/banjo-midison/.venv/bin/banjo-mcp"
    }
  }
}
```

**Claude Code** — add to your project or global settings:

```json
{
  "mcpServers": {
    "banjo-midison": {
      "command": "/absolute/path/to/banjo-midison/.venv/bin/banjo-mcp"
    }
  }
}
```

**Other hosts** (Cursor, Continue, etc.) — consult your host's MCP
documentation. The command is always `.venv/bin/banjo-mcp` from the repo root.

After configuring, restart your MCP host. The two tools should appear.

### Logs

Server logs go to stderr at `INFO` level. To inspect them while developing:

```bash
.venv/bin/banjo-mcp 2> /tmp/banjo-mcp.log
# (in another shell) tail -f /tmp/banjo-mcp.log
```

### Output directory

Files land in `~/Music/banjo/` by default. Change it via the
`set_output_directory` tool:

> "Set the banjo output directory to ~/Music/Ableton/banjo-clips"

That call writes the path to `~/.banjo/config.json` and persists across
restarts.

### About the author

The project was created by [David Ryan](http://davidryan.tech), from the Australian production duo [Trovaire](https://www.wearetrovaire.com), as an assistant for analysis and composition. And not just because he's the drummer. 

If you find this useful, say hello, and be sure to share any music you make with it.