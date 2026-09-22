# Midison

An intelligent MIDI chord progression and groove generator for songwriters and producers. You describe what you want (such as a mood, a reference artist, or a harmonic idea) and Midison produces rich, voice-led MIDI directly in your DAW or files.

It runs as an MCP server, which means your AI assistant (Claude Desktop, Cursor, or any MCP-compatible host) becomes your composition co-producer. You talk to Claude, Claude calls Midison, and voice-led clips appear directly in your active Ableton session or your music folder alongside a `.md` harmonic analysis document.

It is not a bloated plugin. It generates self-contained, voice-led MIDI clips with the root anchored in the chord and notes placed in comfortable mixing registers.

## Setup

```bash
git clone https://github.com/ddri/midison.git
cd midison
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Run the test suite

```bash
uv run pytest
```

173 tests covering the parser, chord builder, voicings, voice leading, grooves, virtual MIDI streaming, AbletonOSC injection, Live 12 MIDI Tools, MIDI writer, config, CLI, and MCP server.

## Command-line interface

Render progressions directly to MIDI files, stream them live into your DAW, or inject clips directly:

```bash
# Basic progression (C major, 120 BPM, 4 beats per chord)
midison "ii7 - V7 - Imaj7"

# Stream live into your armed Ableton synth via virtual MIDI port 'Midison'
midison "ii7 - V7 - Imaj7" -k Eb -v drop2 -p bossa --play

# Continuous jam loop (Ctrl+C to stop)
midison "i7 - iv7 - v7 - i7" -k C -m minor -p charleston --play --loop

# Inject directly into Ableton Live Track 1, Clip 1 via AbletonOSC (zero drag-and-drop)
midison "Imaj9 - vi9 - ii9 - V13" -k Eb --to-ableton --track 0 --clip 0

# Install the Live 12 Piano Roll Generator directly into Ableton
midison --install-m4l

# Install AbletonOSC into your Ableton User Remote Scripts
midison --install-ableton-osc

# Per-chord duration using numeral:beats syntax
midison "ii7:2 - V7:2 - Imaj7:4" -k G --bpm 105 --pattern strum
```

Files land in `~/Music/midison/` by default alongside `.md` sidecars.

## Generate the audition corpus

```bash
midison-corpus
# or: uv run python -m midison.corpus
```

Writes 12 `.mid` files plus `.md` sidecars to `./output/` by default. Drag them into your DAW to hear what the theory engine produces across different styles and voicings.

```bash
midison-corpus --output-dir ~/Music/midison-test
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

`midison-mcp` is a stdio-transport MCP server. Point your MCP host at it and the tools become available to your AI assistant.

### Connecting

**Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "midison": {
      "command": "/absolute/path/to/midison/.venv/bin/midison-mcp"
    }
  }
}
```

**Claude Code / Cursor** — add to your project or global MCP settings:

```json
{
  "mcpServers": {
    "midison": {
      "command": "/absolute/path/to/midison/.venv/bin/midison-mcp"
    }
  }
}
```

Restart your MCP host after configuring. The five tools will appear.

### Tools

* **`generate_midi_progression`**: Generates a `.mid` file and `.md` sidecar from a Roman numeral progression.
* **`send_to_ableton`**: Directly injects a progression into an active Ableton Live track and clip slot via AbletonOSC (zero drag-and-drop).
* **`stream_to_midi_port`**: Streams notes in real-time to a macOS CoreMIDI virtual port (`"Midison"`) to audition through armed VST instruments live.
* **`install_ableton_integrations`**: Automatically installs AbletonOSC and the Live 12 Max Generator into your Ableton User Library.
* **`set_output_directory`**: Sets where MIDI files are written (persisted to `~/.midison/config.json`).

#### `generate_midi_progression` & `send_to_ableton` Parameters

Required fields: `key_center`, `scale_type`, `bpm`, `chords`.

Top-level optional fields:

| Field | Default | Description |
|-------|---------|-------------|
| `track_index` | `0` | *(send_to_ableton only)* Target Ableton track index (0 = Track 1). |
| `clip_index` | `0` | *(send_to_ableton only)* Target Ableton clip slot index (0 = Slot 1). |
| `fire` | `true` | *(send_to_ableton only)* Automatically launch/play the clip in Ableton after injection. |
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
| `pattern` | `"block"` | Playback rhythm pattern / comping groove — see grooves below. |
| `inversion` | — | Override inversion: 0 = root, 1 = first, 2 = second, 3 = third. |

## Zero-Friction Ableton Live Workflows

No more exporting files to a folder and dragging clips into your DAW. Midison supports three native, zero-drag workflows:

### 1. Real-time Virtual MIDI Streaming
Streams voice-led progressions in real time to a macOS CoreMIDI virtual port named **`Midison`**:
* **Ableton Setup:** Arm any instrument track (e.g. loaded with Serum, Keyscape, or Diva) and set **MIDI From** to **`Midison`**.
* **Usage:** Run `midison "ii7 - V7 - Imaj7" -k Eb -v drop2 -p bossa --play` or ask Claude Desktop to audition a progression using the `stream_to_midi_port` tool. Notes play through your synth live with zero latency.

### 2. Direct AbletonOSC Clip Injection
Directly instantiates and populates MIDI clips inside your active Ableton Live session over local OSC:
* **One-time Setup:** Run `midison --install-ableton-osc`. In Ableton Live, open **Settings (Cmd + ,) > Link/Tempo/MIDI**, and select **AbletonOSC** under **Control Surface**.
* **Usage:** Run `midison "ii7 - V7 - Imaj7" --to-ableton --track 0 --clip 0` or ask Claude: *"Drop an 8-bar progression into Track 1, Clip Slot 1 in Ableton and hit play."* The clip appears immediately in your session and begins looping.

### 3. Native Live 12 Piano Roll Generator
A native Max for Live MIDI Tool that lives inside Ableton Live 12's Piano Roll:
* **One-time Setup:** Run `midison --install-m4l` (installs `Midison Generator.amxd` to `~/Music/Ableton/User Library/MIDI Tools/Max Generators/`).
* **Usage:** In Ableton Live 12, double-click any MIDI clip slot to open the Piano Roll, click the **Generators** tab, and select **Midison Generator** to compose chords and voicings directly inside Live with zero external dependencies.

### Grooves & Rhythmic Patterns

Midison separates harmonic voicings from performance patterns. Pass `--pattern <name>` on the CLI or `pattern: "<name>"` via MCP:

| Pattern | Description |
|---------|-------------|
| `block` | Sustained chord hold across the duration (default). |
| `strum` | Staggered 15ms guitar/harp onset delay from bass to treble. |
| `arpeggio_up` | Sequential ascending note steps. |
| `arpeggio_down` | Sequential descending note steps. |
| `charleston` | Dotted-quarter (beat 1) + eighth-note stab (and-of-2) (Jazz, Neo-soul, House). |
| `four_on_floor` | Quarter-note stabs with alternating velocity accents (Indie rock, House). |
| `bossa` | Brazilian Bossa Nova syncopation ($E(5,16)$) with bass on half notes and offbeat chord stabs. |
| `tresillo` | 3+3+2 syncopation on beats 0.0, 1.5, 3.0 (Latin, Afrobeats, Pop). |
| `reggae_skank` | Upbeat offbeat chops on the "and" of the beat (Reggae, Dub, Ska). |
| `waltz` | 3/4 meter comping: bass on beat 1, upper chord chops on beats 2 and 3. |
| `comp_syncopated` | Syncopated comping pulses on beats 0.0, 1.5, and 3.0. |

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
.venv/bin/midison-mcp 2> /tmp/midison-mcp.log
tail -f /tmp/midison-mcp.log
```

## Roman numeral grammar

- **Triad qualities:** `I` (major), `i` (minor), `vii°` / `viio` (diminished), `III+` (augmented)
- **Extensions:** `7`, `maj7`, `9`, `11`, `13`, `maj9`, `maj13`
- **Alterations:** `b5`, `#5`, `b9`, `#9`, `#11`, `b13`
- **Chromatic roots / modal mixture:** `bVII`, `bIII`, `bVI`, `bII`, `#IV`
- **Secondary dominants:** `V/vi`, `V7/ii`, `vii°/V`
- **Half-diminished:** `iiø`
- **Inversions:** `V6` (first), `V64` (second), `V42` (third of seventh chord)

Supported modes: major, minor, dorian, phrygian, lydian, mixolydian, locrian, harmonic_minor, melodic_minor, phrygian_dominant, lydian_dominant, altered.

## Architecture

```
src/midison/
├── theory.py         # Roman numeral parser, modes, chord builder
├── voicings.py       # Voicing transformations (close, drop2, drop3, drop2and4, spread)
├── voice_leading.py  # Inversion + register optimisation
├── grooves.py        # Comping grooves and performance pattern engine
├── events.py         # Timed note event resolution (pitch, start_beat, duration, velocity)
├── stream.py         # Real-time macOS CoreMIDI virtual port streaming
├── ableton.py        # AbletonOSC direct clip injection client and installer
├── miditool.py       # Ableton Live 12 native dictionary formatter and AMXD builder
├── midi_writer.py    # MIDI output, sidecar generation, generation pipeline
├── cli.py            # Standalone one-shot CLI generator and installer
├── mcp_server.py     # MCP stdio server with 5 production tools
├── corpus.py         # Audition corpus CLI
└── config.py         # Persistent config (~/.midison/config.json)
```

## About

Created by [David Ryan](http://davidryan.tech) of the Australian production duo [Trovaire](https://www.wearetrovaire.com) as a composition and harmonic analysis tool. If you find it useful, say hello and share what you make with it.
