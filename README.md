# gtfs-semantic-diff

*日本語版: [README.ja.md](README.ja.md)*

**gtfs-semantic-diff** compares two versions of a GTFS feed and reports the
differences as human-recognizable, semantic changes — a route discontinued,
evening service cut, a stop renamed or relocated, departures shifted — instead
of thousands of changed rows. Every raw field-level difference is structurally
accounted for: it either becomes evidence for a change event or is reported as
an unexplained residual, and the coverage ratio is measured on every run.

Try it: **[diff.gtfs.jp](https://diff.gtfs.jp/)** — upload any two GTFS zips,
free, no sign-up. (The input UI is currently Japanese-first; the report viewer
has an English mode. Full English support is being rolled out — see
[docs/design/i18n.md](docs/design/i18n.md).)

## Features

- **Explanation ledger**: level 0 enumerates every raw difference (all files,
  all fields). Each one must either back a change event as evidence or be
  reported as a residual — so "did we miss something?" has a measurable
  answer (`explained_ratio`, typically 1.0 on our verification feeds).
- **ID-independent matching**: even when `stop_id` / `route_id` / `trip_id`
  are reassigned between versions, entities are re-identified from content —
  names, coordinates, stop sequences, times. The resulting old↔new ID mapping
  is itself an output (`mapping.json`), usable as a backbone for longitudinal
  analysis across feed versions.
- **Reports in cognitive units**: a self-contained HTML report in four parts
  (whole feed / stops / per route / everything else). Route pages show the
  old and new timetables merged in published-timetable format, with added,
  removed and retimed trips marked.
- **Verification view**: every raw difference can be traced from GTFS
  file/row/value to the event that explains it to where it is displayed
  (three-layer traceability).
- **Deterministic, rule-based**: no ML or LLM in detection or classification.
  All thresholds live in `config/default.toml`. Same input, same output.
- **JSON as the stable interface**: the core is a pure function from two
  snapshots to a ChangeEvent JSON stream; HTML, Markdown, the web service,
  the JSON API and the MCP server are all consumers of it.
- **Color-blind aware**: bold, symbols, line styles and numbers are the
  primary channel in every output; color only reinforces.

## Machine-readable outputs and AI integration

The hosted service exposes every layer of a comparison result:

| Layer | URL pattern | Content |
|---|---|---|
| Digest | `r/{pair}.digest.md` / `.digest.json` | Summary for LLMs and humans (currently Japanese; English planned) |
| Route detail | `r/{pair}.routes.digest.json` | Per-route changed trips (old/new trip_ids), counts by time band |
| ID mapping | `r/{pair}.mapping.json` | Adopted old↔new correspondences for stops / routes / trips |
| Full events | see `r/{pair}/index.json` | All 44 event types with evidence, plus raw diffs |

- **MCP server**: `https://diff.gtfs.jp/mcp` — register it as a connector in
  Claude or ChatGPT (no auth) and query comparisons conversationally,
  including running new comparisons.
- Developer guide: [diff.gtfs.jp/developers.html](https://diff.gtfs.jp/developers.html) ·
  API reference: [diff.gtfs.jp/docs/](https://diff.gtfs.jp/docs/README.md) ·
  [llms.txt](https://diff.gtfs.jp/llms.txt)

## Install

Python 3.11+ (developed on 3.14).

```sh
uv venv .venv.nosync --python 3.14   # .nosync needed if the repo is under iCloud sync (see note)
ln -s .venv.nosync .venv
uv pip install -e '.[dev]' --python .venv.nosync/bin/python
```

> **Note (macOS + iCloud)**: if the repository lives under an iCloud-synced
> directory (e.g. `~/Documents`), a venv at `.venv` breaks: iCloud keeps
> restoring a hidden flag on `.pth` files in site-packages, and Python 3.14
> ignores hidden `.pth` files. Directories named `*.nosync` are excluded from
> iCloud sync, hence the layout above.

## Usage

```sh
# Compare two local GTFS zips (older one first) into a self-contained HTML report
gtfs-semantic-diff compare old.zip new.zip --html report.html

# Also emit ChangeEvent JSON / Markdown / raw diffs
gtfs-semantic-diff compare old.zip new.zip \
    -o events.json --report report.md --rawdiffs rawdiffs.json

# Lightweight HTML (same "core" bundle as the web service) or app+data split output
gtfs-semantic-diff compare old.zip new.zip --html-lite lite.html --html-dir out/

# AI-oriented digest (Markdown / JSON, numbers guaranteed identical to the report)
gtfs-semantic-diff compare old.zip new.zip --digest digest.md --digest-json digest.json

# Japanese feeds: fetch generations directly from gtfs-data.jp
gtfs-semantic-diff fetch --org nagai-unyu --feed Nagaibus
gtfs-semantic-diff compare --org chitetsu --feed chitetsubus \
    --old prev_2 --new prev_1 --html report.html

# Run only the L1 identity stage and inspect match confidence
gtfs-semantic-diff identity --org chitetsu --feed chitetsubus
```

- `--config` swaps the threshold TOML (default: `config/default.toml`).
- The web service (`infra/`, AWS CDK; S3 + CloudFront + Lambda) powers
  [diff.gtfs.jp](https://diff.gtfs.jp/) and can be deployed to your own AWS
  account.

## How detection works

Events fall into 6 groups (routes, stop patterns, trips/times, stops,
calendars, fares/metadata), 44 types in total. The exhaustive detection
specification is [docs/spec/detection.md](docs/spec/detection.md) (Japanese):
L0 enumeration rules, L1 identity scoring, and per-rule detection conditions,
evidence consumption and thresholds.

```
zip ×2 | gtfs-data.jp API
  → load/      normalized loading (day_type normalization, all .txt kept as strings)
  → diff0/     L0: exhaustive RawDiff enumeration (the ledger's denominator)
  → identity/  L1: cross-version identity — stop clusters / route families /
               stop patterns / route groups
  → events/    L2: rule cascade + residual accounting → ChangeEvent JSON (canonical)
  → report/    presentation model (cognitive units) → HTML / Markdown / digest
```

## Versioning

Date-based CalVer (`YYYY.M.D.N` — release date plus a same-day sequence
number, e.g. `2026.7.11.1`). `pyproject.toml` is the single source of the
version; it is embedded in generated reports alongside `generated_at`.

## Status (2026-09)

All roadmap milestones are complete. On the Japanese verification feeds
`explained_ratio` is 1.0000; the international verification set (TriMet,
MBTA, STM Montréal, Rome, national-scale Swiss and Netherlands feeds) runs to
completion with explained_ratio 0.98–1.0. 276 tests. The largest Japanese
verification pair (30,700 raw diffs) takes ~2 seconds; national-scale feeds
finish in minutes ([docs/perf/](docs/perf/)).

## Documentation

Most documentation is in Japanese (development happens in Japanese); the
external API guide is being translated (see [docs/design/i18n.md](docs/design/i18n.md)).

| Document | Content |
|---|---|
| [docs/articles/internals_1_core.md](docs/articles/internals_1_core.md) | Internals, part 1: RawDiff, MatchGraph, TripDelta, ChangeEvent — the ledger core |
| [docs/articles/internals_2_presentation.md](docs/articles/internals_2_presentation.md) | Internals, part 2: the presentation layer — from ledger units to cognitive units |
| [docs/spec/detection.md](docs/spec/detection.md) | Detection specification (implementation-accurate, exhaustive) |
| [docs/design/presentation.md](docs/design/presentation.md) | Report display requirements and invariants |
| [docs/design/ontology.md](docs/design/ontology.md) | Event catalog (design) |
| [docs/design/architecture.md](docs/design/architecture.md) | Architecture and JSON schemas |
| [docs/design/roadmap.md](docs/design/roadmap.md) | Milestones and Definitions of Done |
| [docs/api/](docs/api/) | External API guide and reference (also served at [diff.gtfs.jp/docs/](https://diff.gtfs.jp/docs/README.md)) |
| [docs/verification/](docs/verification/) | Real-data verification logs |
| [docs/perf/](docs/perf/) | Performance measurement records |
| [CLAUDE.md](CLAUDE.md) | Design principles and development rules (instructions for AI agents) |

## Development

This repository is developed as a human + AI collaboration using
[Claude Code](https://claude.com/claude-code). [CLAUDE.md](CLAUDE.md) is the
standing instruction file (design principles, development rules); progress is
driven by per-milestone Definitions of Done — nothing is recorded as "done"
without an execution record on the verification feeds. Design decisions,
review findings and rejected alternatives are kept in
[docs/verification/](docs/verification/) and the revision histories of the
design documents.

```sh
.venv.nosync/bin/python -m pytest -q
.venv.nosync/bin/ruff check src tests
```

- Every detection rule ships with: documented detection conditions, a unit
  test on synthetic GTFS, and a visually confirmed example on a real feed.
- No threshold literals in code — everything in `config/default.toml`.
- Changes to detection logic must update docs/spec/detection.md; changes to
  display rules must update docs/design/presentation.md.

## License and attribution

- Code: [MIT License](LICENSE)
- Map tiles: [GSI tiles](https://maps.gsi.go.jp/development/ichiran.html)
  (attribution shown in reports). Map glyphs: Geolonia
- Feed data: open data published by transit agencies (for Japanese feeds, via
  [gtfs-data.jp](https://gtfs-data.jp)). Follow each feed's license terms when
  redistributing reports.
