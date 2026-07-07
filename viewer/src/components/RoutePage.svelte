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
  $: allSystems = page.overview.direction_groups.flatMap((g) =>
    g.systems.map((s) => ({ ...s, dg_kind: g.kind })));
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

  // R18: 曜日タブ。③本数表と④時刻表を選択曜日に絞る (①②は運行日横断なので対象外)
  $: dayTabs = page.day_totals ?? [];
  let selectedDay = null;
  $: if (selectedDay === null && dayTabs.length) selectedDay = dayTabs[0].day_type;
  function tabLabel(d) {
    if (d.old === d.new) return `${dayJa(d.day_type)} ${d.new}${tt("trips_count")}`;
    const sym = d.new > d.old ? "▲" : "▼"; // 記号+数値が第1チャネル (原則5)
    return `${dayJa(d.day_type)} ${d.old}${tt("trips_count")}→${d.new}${tt("trips_count")}${sym}`;
  }
  $: dayMatrix = {
    bands: page.band_matrix.bands,
    rows: page.band_matrix.rows.filter((r) => r.day_type === selectedDay),
  };
  $: dayTimetables = page.timetables.filter((tb) => tb.day_type === selectedDay);
  $: changedTables = dayTimetables.filter((tb) => tb.columns.some(columnChanged));

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

    <!-- 曜日タブ (R18): ③④を選択曜日に絞る。①②は運行日横断なので対象外 -->
    {#if dayTabs.length > 1}
      <div class="day-tabs" role="tablist">
        {#each dayTabs as d}
          <button
            type="button" role="tab" class="day-tab"
            class:active={selectedDay === d.day_type}
            aria-selected={selectedDay === d.day_type}
            on:click={() => (selectedDay = d.day_type)}
          >{tabLabel(d)}</button>
        {/each}
      </div>
    {/if}

    <!-- ③ 時間帯別本数 -->
    {#if dayMatrix.rows.length}
      <h3>{tt("band_table")}</h3>
      <BandMatrix matrix={dayMatrix} />
    {/if}

    <!-- ④ 新旧時刻表 -->
    {#if dayTimetables.length}
      <h3>{tt("timetables")}</h3>
      {#each dayTimetables as tb (`${tb.direction_group}|${tb.leg}|${tb.day_type}`)}
        {@const changed = changedTables.includes(tb)}
        <details class="tt-section" open={changed && changedTables.length <= 4}>
          <summary>
            {tb.label}
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
  /* 曜日タブ: Excel のシート切替をページ左上寄せにした形。
     アクティブは太字+下線+実線枠 (色は補強のみ、原則5) */
  .day-tabs {
    display: flex; flex-wrap: wrap; gap: 0.3rem;
    margin: 0.9rem 0 0.2rem; border-bottom: 2px solid var(--line);
    padding: 0 0 0 0.2rem;
  }
  .day-tab {
    font: inherit; font-size: 0.92em; cursor: pointer;
    border: 1px solid var(--line); border-bottom: none;
    border-radius: 6px 6px 0 0; background: var(--bg-soft);
    color: inherit; padding: 0.3rem 0.8rem; margin-bottom: 0;
  }
  .day-tab.active {
    font-weight: 700; text-decoration: underline;
    text-underline-offset: 0.25em;
    background: #fff; border: 2px solid #1a4f8b; border-bottom: 2px solid #fff;
    margin-bottom: -2px;
  }
  .tt-section { border: 1px solid var(--line); border-radius: 4px; margin: 0.35rem 0; }
  .tt-section > summary { cursor: pointer; padding: 0.3rem 0.6rem; background: var(--bg-soft); }
  .tt-section > :global(.tt-head), .tt-section > :global(p), .tt-section > :global(.tt-wrap) {
    margin: 0.4rem 0.6rem;
  }
</style>
