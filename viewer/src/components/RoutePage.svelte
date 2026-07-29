<script>
  import { lang, t, dayName, formatDateRuns } from "../lib/i18n.js";
  import { countText, runsText } from "../lib/format.js";
  import DateCalendar from "./DateCalendar.svelte";

  // 特定日の運行日がこの日数以上ならカレンダー描画に切り替える
  // (2026-07-29 ユーザー仕様「10日以上くらい」。列挙はカレンダーがあれば不要)
  const CAL_MIN_DAYS = 10;
  import LevSummary from "./LevSummary.svelte";
  import BandMatrix from "./BandMatrix.svelte";
  import DiffTimetable from "./DiffTimetable.svelte";
  import SystemMap from "./SystemMap.svelte";

  export let page;
  export let index; // 章番号
  export let open = false;

  let showMap = false;
  $: tt = $t;
  // R2 改: ①の停車列と地図は leg (時刻表単位・曜日統合) で揃える
  $: allLegs = page.overview.direction_groups.flatMap((g) =>
    (g.legs ?? []).map((l) => ({ ...l, dg_kind: g.kind })));
  $: axisRows = page.overview.direction_groups.flatMap((g) => g.axis_rows ?? []);
  $: keyStops = page.overview.key_stops ?? {};
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
  // 便数表記は countText に一元化 (PI-1/PI-2 — mixed は「のべ」を冠する)
  function tabLabel(d) {
    return `${dayJa(d.day_type)}${addedTo(d)} ${countText(tt, d)}`;
  }
  // M10: 増便/限定型の注記 (dow の曜日集合を包含する day_type が同居する場合)
  function addedTo(d) {
    return d.added_to ? tt("day_added_to", dayJa(d.added_to)) : "";
  }
  $: dayMatrix = {
    bands: page.band_matrix.bands,
    rows: page.band_matrix.rows.filter((r) => r.day_type === selectedDay),
  };
  $: dayTimetables = page.timetables.filter((tb) => tb.day_type === selectedDay);
  // SD5b: 選択タブが複数世界セルならメタ (運行日・対応信号) を出す
  $: cellMeta = page.day_cells?.[selectedDay] ?? null;
  // 引数に meta を取る (Svelte のテンプレート更新は参照変数で追跡されるため、
  // クロージャで cellMeta を読むとタブ切替時に再描画されない)
  function cellDates(m, side) {
    const runs = m[`runs_${side}`];
    const total = m[`dates_${side}_total`];
    if (!runs) {
      // 旧版バンドル互換 (schema_version 0: runs なし)
      const r = formatDateRuns(m[`dates_${side}`] ?? [], $lang);
      return r.text + (r.more ? ($lang === "en" ? ` +${r.more}` : ` ほか${r.more}区間`) : "");
    }
    return runsText(runs, m[`runs_${side}_more`], total, $lang, { withYear: true });
  }
  // カレンダー描画: 日数が閾値以上で、かつランが全区間そろっている
  // (more>0 の旧版バンドルは列挙にフォールバック)
  function calMode(m) {
    if (!m || !m.runs_old && !m.runs_new) return false;
    if (m.runs_old_more || m.runs_new_more) return false;
    return Math.max(m.dates_old_total || 0, m.dates_new_total || 0) >= CAL_MIN_DAYS;
  }
  // SD3 改: 「特定日」タブの具体日付 (新旧同一なら1行に畳む)。
  // 同一判定は cap 前の全日付を代表する runs+total で行う (ui_quality.md B1 —
  // cap 済みリスト比較では先頭30日一致だけで同一と誤判定する)
  $: sameSpecial =
    page.special_dates &&
    page.special_dates.old_total === page.special_dates.new_total &&
    JSON.stringify(page.special_dates.runs_old ?? page.special_dates.old) ===
      JSON.stringify(page.special_dates.runs_new ?? page.special_dates.new);
  function specialRun(side) {
    const sd = page.special_dates;
    const total = sd[`${side}_total`];
    const runs = sd[`runs_${side}`];
    if (runs) {
      // PI-3: サーバー側で全日付から圧縮したラン (cap 後圧縮の誤誘導なし)
      return tt("fo_special_rundates",
                runsText(runs, sd[`runs_${side}_more`], null, $lang,
                         { withYear: true }), total, 0);
    }
    // 旧版バンドル互換 (schema_version 0)
    const r = formatDateRuns(sd[side], $lang);
    const extra = (r.more || 0) + Math.max(0, total - sd[side].length);
    return tt("fo_special_rundates", r.text, total, extra);
  }
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
    return dayName(d, $lang);
  }
  // R19: 折りたたみヘッダ = 曜日別便数 (旧→新、合計は出さない) + 質的チップ。
  // countText 経由なので mixed は折りたたみ時も「のべ」になる (PI-2 —
  // タブだけ直して折りたたみが旧表記のままだった ui_quality.md A2 の再発防止)
  function dayCount(d) {
    return `${dayJa(d.day_type)} ${countText(tt, d)}`;
  }
  function chips(p) {
    const s = p.summary;
    if (s.level1)
      return [s.level1.kind === "added" ? `◆${tt("chip_new")}` : `◆${tt("chip_removed")}`];
    const lt = {};
    for (const d of p.day_totals ?? [])
      for (const [k, v] of Object.entries(d.labels ?? {})) lt[k] = (lt[k] ?? 0) + v;
    const out = [];
    if (s.level2.length) out.push(`◆${tt("chip_systems")}`);
    if ((lt.rerouted ?? 0) + (lt.shortened ?? 0) + (lt.extended ?? 0))
      out.push(`○${tt("chip_reroute")}`);
    if (s.level5.retimed_major) out.push(`＊${tt("chip_retime")}`);
    else if (s.level5.retimed_minor) out.push(`・${tt("chip_minor")}`);
    return out;
  }
  $: chipList = chips(page);
  // R19: 時刻表の折りたたみ行 = 旧→新便数 + ラベル別件数 (変更なしは出さない)
  function tbCount(tb) {
    return countText(tt, { old: tb.trips_old, new: tb.trips_new });
  }
  function tbChips(tb) {
    const names = tt("trip_labels");
    return ["added", "removed", "rerouted", "shortened", "extended", "retimed", "retimed_minor"]
      .filter((k) => tb.label_counts?.[k])
      .map((k) => `${names[k]}${tb.label_counts[k]}`)
      .join("・");
  }
</script>

<details class="chapter" {open} id={"route-" + page.route_group}>
  <summary>
    {index}. {page.route_group}
    <span class="count">
      {(page.day_totals ?? []).map(dayCount).join(" ")}{chipList.length ? ` | ${chipList.join(" ")}` : ""}
    </span>
  </summary>
  <div class="body">
    <!-- M9: 旧名称 (世代間で対応した family) / 廃止・新設ページの類似候補 -->
    {#if page.former_names?.length}
      <p class="meta">{tt("former_names")}: {page.former_names.join("、")}</p>
    {/if}
    {#if page.related_names?.length}
      <!-- 同じ再編成分の旧路線 (便は各自の対応先ページに)。旧名称と区別する -->
      <p class="meta">{tt("related_names")}: {page.related_names.join("、")}</p>
    {/if}
    {#if page.similar_candidates?.length}
      <p class="meta">
        {tt("similar_candidates")}:
        {page.similar_candidates.map((c) => tt("similar_one", c.name, c.similarity)).join(" / ")}
      </p>
    {/if}
    <!-- ① 路線概要 -->
    <h3>{tt("overview")}</h3>
    <!-- ラベル列とバス停列の2カラム。折り返し行はラベル列を空けたまま
         バス停列の縦線が全行で揃う (grid の列幅は最長ラベルに合わせて共有) -->
    <div class="axis-grid">
      {#each axisRows as row}
        <span class="axis-label">{row.label}</span>
        <span class="axis-stops pattern">
          {#each elideByKeyStops(row.stops, keyStops, 11) as s, i}
            {#if i > 0}<span class="arrow">{row.kind === "pair" ? "—" : "→"}</span>{/if}<span class="stop">{s}</span>
          {/each}
        </span>
      {/each}
    </div>
    <details bind:open={showMap}>
      <summary class="meta" style="cursor:pointer">{tt("show_map")}</summary>
      {#if showMap}
        <SystemMap legs={allLegs} keyStops={keyStops} />
      {/if}
    </details>

    <!-- ② 変化のサマリー -->
    <h3>{tt("summary_changes")}</h3>
    <LevSummary {page} />

    <!-- 曜日タブ (R18): ③④を選択曜日に絞る。①②は運行日横断なので対象外。
         運行日区分が1つでも表示する (どの区分の情報かを常に明示) -->
    {#if dayTabs.length >= 1}
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

    <!-- SD5b: 複数世界セルのタブでは、そのセルの運行日と対応の性質を示す。
         日数が CAL_MIN_DAYS 以上ならコンパクトカレンダー (列挙は出さない) -->
    {#if cellMeta}
      <div class="special-dates">
        <p class="sd-line">
          {#if calMode(cellMeta)}
            {#if cellMeta.dates_old_total}
              {tt("old_gen")}: {tt("total_days", cellMeta.dates_old_total)}
            {/if}
            {#if cellMeta.dates_old_total && cellMeta.dates_new_total}&nbsp;→&nbsp;{/if}
            {#if cellMeta.dates_new_total}
              {tt("new_gen")}: {tt("total_days", cellMeta.dates_new_total)}
            {/if}
          {:else}
            {#if cellMeta.dates_old_total}
              {tt("old_gen")}: {cellDates(cellMeta, "old")}
            {/if}
            {#if cellMeta.dates_old_total && cellMeta.dates_new_total}&nbsp;→&nbsp;{/if}
            {#if cellMeta.dates_new_total}
              {tt("new_gen")}: {cellDates(cellMeta, "new")}
            {/if}
          {/if}
          {#if cellMeta.signal === "content"}({tt("cell_same_content")}){/if}
          {#if cellMeta.signal === "flow"}({tt("cell_flow")}){/if}
          {#if cellMeta.mixed_old || cellMeta.mixed_new}
            <br>{tt("cell_mixed")}
            {#if (cellMeta.shared_dates_old ?? []).length || (cellMeta.shared_dates_new ?? []).length}
              {tt("cell_mixed_shared",
                  [...new Set([...(cellMeta.shared_dates_old ?? []), ...(cellMeta.shared_dates_new ?? [])])]
                    .map((s) => `${+s.slice(4, 6)}/${+s.slice(6, 8)}`).join("、"))}
            {/if}
          {/if}
        </p>
        {#if calMode(cellMeta)}
          <DateCalendar oldRuns={cellMeta.runs_old ?? []} newRuns={cellMeta.runs_new ?? []} />
        {/if}
      </div>
    {/if}

    <!-- SD3 改: 「特定日」タブでは、その場でどの日付を指すのかを解説する。
         日数が CAL_MIN_DAYS 以上ならカレンダー (セル注記と同じ規則) -->
    {#if selectedDay === "irregular" && page.special_dates && !cellMeta}
      {@const sd = page.special_dates}
      {@const sdCal = calMode({
        runs_old: sd.runs_old, runs_new: sd.runs_new,
        runs_old_more: sd.runs_old_more, runs_new_more: sd.runs_new_more,
        dates_old_total: sd.old_total, dates_new_total: sd.new_total,
      })}
      <div class="special-dates">
        <p class="sd-line">
          {#if sdCal}
            {#if sd.old_total}
              {tt("old_gen")}: {tt("total_days", sd.old_total)}
            {/if}
            {#if sd.old_total && sd.new_total}&nbsp;→&nbsp;{/if}
            {#if sd.new_total}
              {tt("new_gen")}: {tt("total_days", sd.new_total)}
            {/if}
          {:else if sameSpecial}
            {tt("rp_special_dates", specialRun(sd.new.length ? "new" : "old"))}
          {:else}
            {#if sd.old_total}
              {tt("old_gen")}: {specialRun("old")}{sd.new_total ? " / " : ""}
            {/if}
            {#if sd.new_total}
              {tt("new_gen")}: {specialRun("new")}
            {/if}
          {/if}
        </p>
        {#if sdCal}
          <DateCalendar oldRuns={sd.runs_old ?? []} newRuns={sd.runs_new ?? []} />
        {/if}
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
      {#each dayTimetables as tb (`${tb.direction_group}|${tb.leg}|${tb.day_type}|${tb.sheet ?? 0}`)}
        {@const changed = changedTables.includes(tb)}
        {@const chipsText = tbChips(tb)}
        <details class="tt-section" open={changed && changedTables.length <= 4}>
          <summary>
            {tb.label}{#if tb.sheet_label}<span class="sheet-label">({tb.sheet_label})</span>{/if}
            <span class="count">
              {tbCount(tb)}{chipsText ? ` | ${chipsText}` : ""}
            </span>
          </summary>
          <DiffTimetable table={tb} />
        </details>
      {/each}
    {/if}
  </div>
</details>

<style>
  .special-dates {
    margin: 0.4rem 0 0.2rem;
    padding: 0.2rem 0.6rem;
    border-left: 3px solid var(--fg-soft);
  }
  .special-dates .sd-line { margin: 0 0 0.15rem; }
  .axis-grid {
    display: grid;
    grid-template-columns: max-content 1fr; /* ラベル列幅は最長ラベルで全行共有 */
    column-gap: 0.9em;
    row-gap: 0.35em;
    margin: 0.3rem 0 0.6rem;
    align-items: baseline;
  }
  .axis-label { font-weight: 600; white-space: nowrap; }
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
  .sheet-label { font-weight: 600; margin-left: 0.4em; }
  .tt-section > :global(.tt-head), .tt-section > :global(p), .tt-section > :global(.tt-wrap) {
    margin: 0.4rem 0.6rem;
  }
</style>
