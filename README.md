# Banjo Midison

A MIDI chord progression generator for solo songwriters and producers. You describe what you want (such as a mood, a reference artist, a harmonic idea) and Banjo generates MIDI files you can drag straight into your DAW.

It runs as an MCP server, which means your AI assistant (Claude Desktop, Claude Code, or any MCP-compatible host) becomes the interface. You talk to Claude, Claude calls Banjo, and a `.mid` file appears in your music folder alongside a `.md` document explaining what was generated and why.

It is not a DAW. It is not a plugin. It generates self-contained MIDI clips with the root always in the chord, in a register that sits well in a mix.

## Setup

```bash
git clone https://github.com/ddri/banjo-midison.git
cd banjo-midison
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Run the test suite

```bash
uv run pytest
```

118 tests covering the parser, chord builder, voicings, voice leading, MIDI writer, config, and MCP server.

## Generate the audition corpus

```bash
banjo-corpus
# or: uv run python -m banjo.corpus
```

Writes 12 `.mid` files plus `.md` sidecars to `./output/` by default. Drag them into your DAW to hear what the theory engine produces across different styles and voicings.

```bash
banjo-corpus --output-dir ~/Music/banjo-test
```

| # | What it demonstrates |
|---|----------------------|
| 01 | ii-V-I in C major, close voicings — sanity check |
| 02 | Neo-soul in F with rootless voicing |
| 03 | Neo-soul in Eb with secondary dominant (V7/vi), drop-2 |
| 04 | I-bVII-IV-I in G — modal mixture (mixolydian borrow) |
| 05 | D dorian i9-IV9 vamp — modal harmony |
| 06 | A minor with V7/iv — secondary dominant in minor |
| 07 | ii-V7b9-I in C — altered dominant |
| 08 | Spread voicing in C |
| 09 | E mixolydian funk — modal + extensions |
| 10 | Dm7 - Em7b5 - A7b9 - Dm7 — half-diminished |
| 11 | Drop-2-and-4 in Bb |
| 12 | C - Eb - Ab - Db — heavy chromatic modal mixture |

## MCP server

`banjo-mcp` is a stdio-transport MCP server. Point your MCP host at it and the tools become available to your AI assistant.

### Connecting

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

**Claude Code** — add to your project or global MCP settings:

```json
{
  "mcpServers": {
    "banjo-midison": {
      "command": "/absolute/path/to/banjo-midison/.venv/bin/banjo-mcp"
    }
  }
}
```

**Other hosts** (Cursor, Continue, etc.) — the command is always `.venv/bin/banjo-mcp` from the repo root.

Restart your MCP host after configuring. The two tools will appear.

### Tools

**`generate_midi_progression`**

Generates a `.mid` file and a `.md` sidecar from a Roman numeral progression.

Required fields: `key_center`, `scale_type`, `bpm`, `chords`.

Top-level optional fields:

| Field | Default | Description |
|-------|---------|-------------|
| `octave` | `3` | Root octave. Octave 4 = Ableton's C3 (MIDI 60, middle C). Default 3 places roots one octave below middle C — a comfortable comping register. |
| `max_octave` | `5` | Hard ceiling on chord register. Any chord whose lowest note sits above this octave is shifted down by whole octaves. Applied after voice leading. |
| `time_signature` | `"4/4"` | Time signature as `"N/D"`. |
| `voice_lead` | `false` | When true, each chord's inversion and octave are chosen to minimise voice motion from the previous chord. |
| `humanize` | off | Velocity and timing randomisation. Fields: `velocity_range`, `timing_ms`, `base_velocity` (default 80). |
| `seed` | — | Integer seed for reproducible humanization. Set this when iterating on a progression so you get identical MIDI bytes. |
| `filename` | auto | Output filename without `.mid`. Auto-generated from key + progression + timestamp if omitted. |
| `prompt_context` | — | Written verbatim into the `.md` sidecar. Records what you asked for. |
| `generation_notes` | — | Harmonic or stylistic notes about the choices made. Also written into the sidecar. |

Per-chord fields (inside the `chords` array):

| Field | Default | Description |
|-------|---------|-------------|
| `numeral` | required | Roman numeral — see grammar below. |
| `duration_beats` | required | Duration in beats. |
| `voicing` | `"close"` | How chord tones are arranged. See voicings below. |
| `rootless` | `false` | Omit the root note. Use this when a separate bass track covers the root. Not valid with `voicing: "spread"`. |
| `inversion` | — | Override inversion: 0 = root, 1 = first, 2 = second, 3 = third. |

**`set_output_directory`**

Sets where MIDI files are written. Persisted to `~/.banjo/config.json` across restarts. Default is `~/Music/banjo/`, created on first write.

### Voicings

| Name | Sound |
|------|-------|
| `close` | Stacked thirds, compact. Default. |
| `drop2` | Second-from-top voice dropped an octave. Slightly more open and warm. |
| `drop3` | Third-from-top voice dropped an octave. Fuller spread. |
| `drop2and4` | Second and fourth from top dropped an octave. Wide and open. |
| `spread` | Root dropped an octave below the upper structure. Good for a strong bass note with upper chord tones above. |

All voicings include the root. To omit the root, set `rootless: true` on the chord.

### Voice leading

When `voice_lead: true`, each chord after the first has its inversion and octave register chosen to minimise semitone movement from the previous chord. The pipeline is:

1. Build chord (close position)
2. Apply voicing (`drop2`, `spread`, etc.)
3. Apply voice leading (choose inversion + register)
4. Apply `rootless` if set
5. Apply `max_octave` clamp

Explicit inversions (via numeral form (`V64`) or the `inversion` field) are pinned and not changed by voice leading.

### Output files

Every generation produces two files:

- `<name>.mid` — the MIDI clip, one track, all chords
- `<name>.md` — the prompt context, generation notes, parameters, and a chord-by-chord table of resolved pitches, voicing, and inversion

### Logs

```bash
.venv/bin/banjo-mcp 2> /tmp/banjo-mcp.log
tail -f /tmp/banjo-mcp.log
```

## Roman numeral grammar

- **Triad qualities:** `I` (major), `i` (minor), `vii°` / `viio` (diminished), `III+` (augmented)
- **Extensions:** `7`, `maj7`, `9`, `11`, `13`, `maj9`, `maj13`
- **Alterations:** `b5`, `#5`, `b9`, `#9`, `#11`, `b13`
- **Chromatic roots / modal mixture:** `bVII`, `bIII`, `bVI`, `bII`, `#IV`
- **Secondary dominants:** `V/vi`, `V7/ii`, `vii°/V`
- **Half-diminished:** `iiø`
- **Inversions:** `V6` (first), `V64` (second), `V42` (third of seventh chord)

Supported modes: major, minor, dorian, phrygian, lydian, mixolydian, locrian, lydian_dominant, phrygian_dominant.

## Architecture

```
src/banjo/
├── theory.py         # Roman numeral parser, modes, chord builder
├── voicings.py       # Voicing transformations (close, drop2, drop3, drop2and4, spread)
├── voice_leading.py  # Inversion + register optimisation
├── midi_writer.py    # MIDI output, sidecar generation, generation pipeline
├── mcp_server.py     # MCP stdio server
├── corpus.py         # Audition corpus CLI
└── config.py         # Persistent config (~/.banjo/config.json)
```

## About

Created by [David Ryan](http://davidryan.tech) of the Australian production duo [Trovaire](https://www.wearetrovaire.com) as a composition and harmonic analysis tool. If you find it useful, say hello and share what you make with it.
