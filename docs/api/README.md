# Using gtfs-semantic-diff from outside — a guide

*日本語版: [README.ja.md](README.ja.md)*

This directory documents how to use gtfs-semantic-diff **from programs, AIs
and external systems** (on the web, https://diff.gtfs.jp/developers.html is
the introduction page; this document is served under /docs/). It is written
both for humans and to be handed to an LLM as context. The precise
specification lives in [reference.md](reference.md).

## What this tool does

It compares two versions of a GTFS feed (bus schedule data) and extracts the
changes as **meaning people can recognize** — route discontinued, service
reduced, rerouting, stop renamed, platform changed and so on: **44
ChangeEvent types**. Its distinguishing feature is the **explanation
ledger**: every raw difference between the two versions (all files, all
fields) must either back an event as evidence or be counted as an
unexplained residual, and the coverage ratio (explained_ratio) is always
published. **How much is explained, and what is not, is guaranteed as a
number** — that is what separates this from a plain diff tool.

Detection is deterministic and rule-based; no LLM or machine learning is
involved in the core. The same input always yields the same output. All
thresholds live in a configuration file.

## What you can do with it (use cases)

- **Data error checking**: use residuals (UNEXPLAINED_RESIDUAL), ID
  reassignments (TECHNICAL_ID_CHURN) and the ledger numbers to hunt down
  feed-authoring mistakes (mis-assigned service_ids, duplicated stops, ...).
- **Summaries and rider notices**: use the events and numbers (which route
  lost how many trips, which stops were renamed) as the raw material for
  human-facing prose. Facts and numbers come from this tool's output; the
  writing is done by the consumer (human or LLM).
- **Cross-checking official announcements**: verify that every item in an
  operator's revision notice is reflected in the data — and that the data
  contains no changes missing from the notice.
- **Research and analysis**: aggregate service reductions, network
  restructurings and service-day changes across regions and over time —
  input for studies on driver shortages, transit deserts and more.
- **A building block for diff-resilient systems**: mapping.json (the ID
  correspondence tables) lets you join stop_id / route_id / trip_id across
  versions — longitudinal ridership analysis, carrying hand-maintained
  assets like shapes.txt forward to a new version, configuration migration:
  a foundation for any system troubled by "the keys change every feed
  update".

## The output layers — which one to use

| Layer | Contents | Good for | Typical size |
|---|---|---|---|
| digest | Whole-feed summary + one summary line per route. No IDs | Notices, cross-checks. Hand this to an LLM first | tens–hundreds of KB |
| routes.digest.json | Detail for every route (changed-trip records, counts by time band, trip_ids) | Drilling into a route | up to a few MB |
| mapping.json | **Old↔new correspondence tables** for stop_id / route_id / trip_id | Backbone for longitudinal joins and asset carry-over | up to a few MB |
| events.json | Every ChangeEvent + evidence + the ledger | Error checking, programmatic use. **The stable interface** | tens of MB |
| rawdiffs.json | Every raw diff (L0) | Residual inspection, full verification | hundreds of MB |

Rule of thumb: **broad, shallow uses read the upper layers; narrow, deep
uses go lower**. The HTML report (viewer) is for humans; its internal data
(bundle) is not a stable interface — programs should use events.json.

## Quick start

### CLI (local)

```bash
# Fetch two versions from gtfs-data.jp and compare (local zips also work)
gtfs-semantic-diff compare --org nagai-unyu --feed Nagaibus \
    --old prev_2 --new prev_1 \
    --digest digest.md -o events.json --html report.html
```

- `digest.md` — the AI digest (a summary you can hand straight to an LLM;
  `--digest-json` for JSON)
- `events.json` — all events + the explanation ledger, machine-readable
- `report.html` — the self-contained viewer (open in a browser)

To drill into one route: `--digest-route "ROUTE NAME" --digest route.md`
(lists every changed trip with trip_ids). All routes at once:
`--digest-routes routes.json`; ID mapping tables: `--mapping mapping.json`.

To compare two local zips: `compare old.zip new.zip` (older one first).

### Web API (https://diff.gtfs.jp/)

```bash
# 1) Submit a comparison job (uid = the version's full UUID on gtfs-data.jp)
curl -X POST https://diff.gtfs.jp/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"type":"gtfs_data_jp","org":"nagai-unyu","feed":"Nagaibus",
       "old_uid":"<full-uid>","new_uid":"<full-uid>"}'
# → {"job_id": "<pair>", "status_url": "/api/jobs/<pair>"}

# 2) Poll until succeeded
curl https://diff.gtfs.jp/api/jobs/<pair>

# 3) Artifacts (versioned, immutable)
#    Report:        https://diff.gtfs.jp/r/<pair>.html
#    Digest:        https://diff.gtfs.jp/r/<pair>.digest.en.md (latest, English;
#                   .digest.md is Japanese — hand one of these to an LLM first)
#    Events JSON:   https://diff.gtfs.jp/r/<pair>/v/<version>.events.json
#    Raw diffs:     https://diff.gtfs.jp/r/<pair>/v/<version>.rawdiffs.json
```

Instead of uids you can submit `"old_rid":"prev_1","new_rid":"current"`.
The list of computed pairs is in the **feed ledger**
`https://diff.gtfs.jp/feeds/<org>__<feed>.json`; every artifact URL of a
pair is in the **pair ledger** `…/r/<pair>/index.json` under
versions[].artifacts (no need to memorize URL rules).

Finding uids (version list on gtfs-data.jp):

```bash
curl "https://diff.gtfs.jp/api/gtfs/feeds?pref=10"          # feeds by prefecture
curl "https://diff.gtfs.jp/api/gtfs/files?org=nagai-unyu&feed=Nagaibus"  # versions
```

## MCP server (for AI agents)

`https://diff.gtfs.jp/mcp` — a Model Context Protocol endpoint. No
authentication. It exposes the same surface as the HTTP layer above, as
tools: exploration (find_feeds / find_generations / list_pairs), summaries
(get_digest / list_routes / get_route_detail / get_stop_changes /
get_residuals), ID correspondence (map_ids), event search (get_events), and
**running comparisons** (run_compare / get_job_status — uncomputed version
pairs can be computed on the spot; a daily rate guard applies). Text tools
take lang="en" (default) or "ja".

- **Claude**: Settings → Connectors → Add custom connector → enter the URL
- **ChatGPT**: Settings → enable Developer mode → add a connector
- Speaks both the 2026-07-28 protocol and the legacy (initialize-style)
  generation

## Recipes by use case

### Error checking (feed authors)

1. Look at `accounting.explained_ratio` in events.json. The closer to 1.0,
   the more of the diff has been given meaning. Check
   `residual_breakdown_by_file` for where residuals live.
2. List events with `type == "UNEXPLAINED_RESIDUAL"` and
   `TECHNICAL_ID_CHURN`. Mass ID reassignment means trip_ids / service_ids
   were regenerated with identical content (harmless in itself, but worth
   confirming it was intentional).
3. From each event's `evidence` (a list of rawdiff IDs), follow into
   rawdiffs.json to see exactly which GTFS file and row backs it.

### Summarizing a revision (translation into prose)

1. Filter events.json by `severity` (major > minor > info) and `type`.
   Route and stop names are in `subject` (display names:
   `display_name_ja` / `display_name_en`).
2. Take numbers from `quantification` (trip counts, ratios, day counts).
   **The prose generator must not recompute** — facts always come from the
   output.
3. The digest (`--digest`) is this procedure pre-baked into one file. Use
   it first.

### Cross-checking (against official notices)

For each item in the notice (e.g. "route X reduced from April 1"), find the
corresponding SERVICE_REDUCED / PATTERN_TRUNCATED events for that route in
events.json. For the reverse direction (changes in the data missing from
the notice), list severity=major events and compare against the notice.

## Recommendations when handing output to an AI

- Passing a report URL (`…/r/<pair>.html`) to an AI works — the HTML's
  `link rel="alternate"` and the site's `/llms.txt` steer it to the digest.
  The most reliable is to pass `…/r/<pair>.digest.en.md` directly.
- Start with the digest; hand over the relevant part of events.json only
  when deeper detail is needed. Full events.json reaches tens of MB on
  large feeds — filter by `type` or `subject` first.
- Passing the event-type catalog in [reference.md](reference.md) alongside
  stabilizes interpretation.
- Have the AI quote facts and numbers only from the JSON output and never
  fill gaps by guessing (the same principle this tool is built on).

## Constraints and cautions

- A comparison is always one old→new pair. Multi-version timelines are not
  supported yet.
- Web jobs consume compute; do not mass-submit automatically. A daily job
  limit applies and returns 429 with Retry-After when exceeded (re-reading
  cached pairs costs nothing). For bulk research workloads, run the CLI
  locally.
- The web service has a size limit: uploads are capped at 100MB per zip, and
  feeds whose uncompressed stop_times.txt exceeds ~100MB per version
  (national aggregate feeds and the like) are declined at submission with
  a 400 and an explanation. The CLI produces the same report locally with
  no size limit.
- Japanese text in the output comes from the data itself (stop and route
  names). Event type IDs and JSON keys are English and stable.
