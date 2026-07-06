<script>
  import { t } from "../lib/i18n.js";
  import LevSummary from "./LevSummary.svelte";
  import BandMatrix from "./BandMatrix.svelte";
  import DiffTimetable from "./DiffTimetable.svelte";
  import SystemMap from "./SystemMap.svelte";

  export let page;
  export let index; // 章番号
  export let open = false;

  let showMap = false;
  $: tt = $t;
  $: allSystems = page.overview.direction_groups.flatMap((g) => g.systems);
  $: canonicalStops = allSystems.length
    ? allSystems.reduce((a, b) =>
        (b.trips_new + b.trips_old > a.trips_new + a.trips_old ? b : a)).stops
    : [];
  $: keyStops = page.overview.key_stops ?? {};
  $: repStops = elideByKeyStops(canonicalStops, keyStops, 11);
  function columnChanged(c) {
    if (c.status === "added" || c.status === "removed") return true;
    if (c.status === "retimed" || c.status === "rerouted")
      return (c.changed_positions?.length ?? 0) > 0;
    return false;
  }
  $: changedTables = page.timetables.filter((tb) => tb.columns.some(columnChanged));

  // 主要停留所 (key_stops の tier) を残して間を省略。地図のラベル段階と同じ基準を共有
  function elideByKeyStops(stops, keys, maxN) {
    if (stops.length <= maxN) return stops;
    let keepTier = 2;
    let kept = stops.map((s, i) => ({ s, i })).filter(
      ({ s, i }) => i === 0 || i === stops.length - 1 || (keys[s] ?? 3) <= keepTier);
    if (kept.length > maxN) {
      keepTier = 1;
      kept = stops.map((s, i) => ({ s, i })).filter(
        ({ s, i }) => i === 0 || i === stops.length - 1 || (keys[s] ?? 3) <= keepTier);
    }
    if (kept.length > maxN) {
      // それでも多ければ等間隔に間引く (先頭末尾は保持)
      const step = (kept.length - 1) / (maxN - 1);
      kept = Array.from({ length: maxN }, (_, k) => kept[Math.round(k * step)]);
    }
    const out = [];
    let prev = -1;
    for (const { s, i } of kept) {
      if (prev >= 0 && i > prev + 1) out.push(`…(${i - prev - 1}停)…`);
      out.push(s);
      prev = i;
    }
    return out;
  }
  function dayJa(d) {
    return tt(d) === d ? d : tt(d);
  }
  function marks(p) {
    const s = p.summary;
    if (s.level1) return s.level1.kind === "added" ? "◆新設" : "◆廃止";
    const out = [];
    if (s.level2.length) out.push("◆系統");
    if (s.level3.some((u) => !u.absorbed_into_level2)) out.push("○経由");
    if (s.level4.length) out.push("▲▼便数");
    if (!out.length && (s.level5.retimed_trips || s.level5.notes.length)) out.push("・微調整");
    return out.join(" ");
  }
</script>

<details class="chapter" {open}>
  <summary>
    {index}. {page.route_group}
    <span class="count">
      {marks(page)}
      ({page.overview.trip_totals.old}→{page.overview.trip_totals.new}{tt("trips_count")})
    </span>
  </summary>
  <div class="body">
    <!-- ① 路線概要 -->
    <h3>{tt("overview")}</h3>
    <p class="pattern">
      {#each repStops as s, i}
        {#if i > 0}<span class="arrow">→</span>{/if}<span class="stop">{s}</span>
      {/each}
    </p>
    <ul class="meta systems-list">
      {#each page.overview.direction_groups as dg}
        <li>
          {dg.label}
          {#if dg.systems.length > 1}
            — {dg.systems.length} {tt("systems")}:
            {#each dg.systems as s, i}
              {i > 0 ? " / " : ""}{s.first_stop}→{s.last_stop}
              ({s.trips_old}→{s.trips_new}{tt("trips_count")}{#if s.status === "added"}・{tt("col_added")}{/if}{#if s.status === "removed"}・{tt("col_removed")}{/if})
            {/each}
          {/if}
        </li>
      {/each}
    </ul>
    <details bind:open={showMap}>
      <summary class="meta" style="cursor:pointer">{tt("show_map")}</summary>
      {#if showMap}
        <SystemMap systems={allSystems} keyStops={keyStops} />
      {/if}
    </details>

    <!-- ② 変化のサマリー -->
    <h3>{tt("summary_changes")}</h3>
    <LevSummary {page} />

    <!-- ③ 時間帯別本数 -->
    {#if page.band_matrix.rows.length}
      <h3>{tt("band_table")}</h3>
      <BandMatrix matrix={page.band_matrix} />
    {/if}

    <!-- ④ 新旧時刻表 -->
    {#if page.timetables.length}
      <h3>{tt("timetables")}</h3>
      {#each page.timetables as tb}
        {@const changed = changedTables.includes(tb)}
        <details class="tt-section" open={changed && changedTables.length <= 4}>
          <summary>
            {tb.label} — {dayJa(tb.day_type)}
            <span class="count">
              {tb.columns.length}{tt("trips_count")}{changed ? " ＊" : ""}
            </span>
          </summary>
          <DiffTimetable table={tb} />
        </details>
      {/each}
    {/if}
  </div>
</details>

<style>
  .systems-list { margin: 0.2rem 0 0.6rem; }
  .tt-section { border: 1px solid var(--line); border-radius: 4px; margin: 0.35rem 0; }
  .tt-section > summary { cursor: pointer; padding: 0.3rem 0.6rem; background: var(--bg-soft); }
  .tt-section > :global(.tt-head), .tt-section > :global(p), .tt-section > :global(.tt-wrap) {
    margin: 0.4rem 0.6rem;
  }
</style>
