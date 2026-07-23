<script>
  import { lang, t, dayName, formatDateRuns } from "../lib/i18n.js";
  import CalendarView from "./CalendarView.svelte";

  export let overview; // presentation.feed_overview
  export let feed = {}; // meta.feed (期間)
  export let catalog = {}; // イベントタイプ表示名

  $: tt = $t;
  $: nameOf = (type) => catalog[type]?.[$lang === "ja" ? "ja" : "en"] ?? type;

  function delta(o, n) {
    if (o == null || n == null || o === n) return "";
    return n > o ? `▲+${n - o}` : `▼${n - o}`;
  }
  function rowChanged(f) {
    return (
      f.status !== "continued" || f.rows_old !== f.rows_new ||
      f.row_added || f.row_removed || f.field_changed || f.column_changes
    );
  }
  // フィード級イベントの読み下し (イベント種別ごとの整形。原文は検証モードで)
  const isoDate = (s) =>
    String(s ?? "").replace(/\b(\d{4})(\d{2})(\d{2})\b/g, "$1-$2-$3");
  function dayLabel(d) {
    return dayName(d, $lang);
  }
  // M10 → SD3: 特定日・運行日なし service の内訳の1行。
  // 実効運行日の具体日付 (date_list) があれば「運行日: 7/21、8/11〜8/16」と
  // 連続日を範囲に畳んで表示する。無い旧バンドルは日数+期間表示に退避
  function specialLine(s) {
    const parts = [dayLabel(s.day_type)];
    if (s.date_list?.length) {
      const runs = formatDateRuns(s.date_list, $lang);
      const extra = (runs.more || 0) + (s.truncated ? s.dates - s.date_list.length : 0);
      parts.push(tt("fo_special_rundates", runs.text, s.dates, extra));
    } else if (s.dates) {
      parts.push(tt("fo_special_dates", s.dates, isoDate(s.first_date), isoDate(s.last_date)));
    }
    parts.push(`${s.trips}${tt("trips_count")}`);
    if (s.day_type === "inactive") parts.push(tt("fo_special_inactive"));
    else if (s.replaces_regular) parts.push(tt("fo_special_replaces"));
    else if (s.dates) parts.push(tt("fo_special_extra"));
    return parts.join("・");
  }
  $: scope = overview.comparison_scope;
  $: specials = [
    ...(overview.special_days?.new ?? []).map((s) => ({ ...s, gen: "new" })),
    ...(overview.special_days?.old ?? [])
      .filter((s) => !(overview.special_days?.new ?? []).some((n) => n.service_id === s.service_id))
      .map((s) => ({ ...s, gen: "old" })),
  ];
  function detail(e) {
    const q = e.quantification || {};
    const files = (e.subject?.files || []).join(", ");
    switch (e.type) {
      case "FEED_VALIDITY_CHANGED": {
        // calendar.txt (changed_rows) と feed_info.txt (changed_fields) の2系統
        const parts = [];
        if (q.changed_rows) parts.push(`${files}: ${tt("fo_ev_changes", q.changed_rows)}`);
        for (const [col, ov] of Object.entries(q.changed_fields || {}))
          parts.push(`${col}: ${isoDate(ov)}`);
        return parts.join(" / ") || files;
      }
      case "HOLIDAY_EXCEPTION_CHANGED": {
        const within = q.within_overlap || 0;
        const outside = (q.outside_overlap || 0) + (q.unknown_window || 0);
        const win = q.overlap_window;
        const parts = [dayLabel(e.subject?.day_type ?? "")];
        if (q.substantive && win) {
          parts.push(`${tt("fo_hx_window", isoDate(win[0]), isoDate(win[1]))} ${within}件`);
        } else {
          parts.push(tt("fo_hx_none"));
        }
        if (outside) parts.push(tt("fo_hx_mechanical", outside));
        return parts.filter(Boolean).join("、");
      }
      case "FARE_CHANGED": {
        const parts = [];
        const pc = q.price_changes || [];
        if (pc.length) {
          const ex = pc.slice(0, 3).map((c) => tt("fo_yen", c.old_price, c.new_price));
          parts.push(`${tt("fo_fare_price", pc.length)} (${ex.join(", ")}${pc.length > 3 ? ", …" : ""})`);
        }
        if (q.removed_fares?.length) parts.push(tt("fo_fare_removed", q.removed_fares.length));
        if (q.added_fares?.length) parts.push(tt("fo_fare_added", q.added_fares.length));
        if (q.fare_rules_diffs) parts.push(tt("fo_fare_rules", q.fare_rules_diffs));
        return parts.join("、");
      }
      case "DAYTYPE_RESTRUCTURED": {
        const o = (e.old_ref?.day_types || []).map(dayLabel).join("・");
        const n = (e.new_ref?.day_types || []).map(dayLabel).join("・");
        return `${o}${tt("fo_daytypes_arrow")}${n}`;
      }
      case "AGENCY_INFO_CHANGED":
      case "TRANSLATION_CHANGED": {
        const parts = [];
        for (const [col, ov] of Object.entries(q.changed_fields || {}))
          parts.push(`${col}: ${isoDate(ov)}`);
        if (!parts.length && e.evidence_count)
          parts.push(tt("fo_ev_changes", e.evidence_count));
        return [files, parts.join(" / ")].filter(Boolean).join(" — ");
      }
      default: {
        // フォールバック: オブジェクトの生表示 ([object Object]) は避け、
        // スカラー値と件数だけを出す。詳細は検証モードが受け持つ
        const parts = [];
        for (const [k, v] of Object.entries(q)) {
          if (Array.isArray(v)) parts.push(`${k}: ${v.length}`);
          else if (typeof v !== "object" || v === null) parts.push(`${k}: ${v}`);
        }
        const subj = Object.values(e.subject || {})
          .filter((v) => typeof v === "string").join(" ");
        return [subj, parts.join(" / ")].filter(Boolean).join(" — ");
      }
    }
  }
</script>

{#if feed.old_period?.[0] || feed.new_period?.[0]}
  <p>
    <strong>{tt("fo_period")}</strong>:
    {feed.old_period?.[0] ?? "?"} 〜 {feed.old_period?.[1] ?? "?"}
    → {feed.new_period?.[0] ?? "?"} 〜 {feed.new_period?.[1] ?? "?"}
  </p>
{/if}

{#if scope}
  <!-- SD2: 同梱世代フィード (改正前後を1ファイルに同梱) の比較範囲の明示。
       記号▮を第1チャネルに (色弱原則)。単一世代の比較では出ない -->
  <div class="scope-note">
    <p><strong>▮ {tt("fo_scope_title")}</strong></p>
    <ul>
      <li>{tt("fo_scope_window", isoDate(scope.comparison_window?.[0]), isoDate(scope.comparison_window?.[1]))}</li>
      {#if scope.primary_periods?.length}
        <li>{tt("fo_scope_primary", scope.primary_periods.map((p) => `${isoDate(p[0])}〜${isoDate(p[1])}`).join(", "))}</li>
      {/if}
      {#if scope.identical_periods?.length}
        <li>{tt("fo_scope_identical", scope.identical_periods.map((p) => `${isoDate(p[0])}〜${isoDate(p[1])}`).join(", "))}</li>
      {/if}
      {#if scope.excluded?.old_services?.length}
        <li>{tt("fo_scope_excluded_old", scope.excluded.old_services.length, scope.excluded.old_trips)}</li>
      {/if}
      {#if scope.excluded?.new_services?.length}
        <li>{tt("fo_scope_excluded_new", scope.excluded.new_services.length, scope.excluded.new_trips)}</li>
      {/if}
    </ul>
  </div>
{/if}

<h3>{tt("fo_files")}</h3>
<div class="scroll-x">
  <table class="fo-table">
    <thead>
      <tr>
        <th>{tt("fo_file")}</th>
        <th class="num">{tt("fo_rows")}</th>
        <th class="num">{tt("fo_added")}</th>
        <th class="num">{tt("fo_removed")}</th>
        <th class="num">{tt("fo_changed")}</th>
      </tr>
    </thead>
    <tbody>
      {#each overview.files as f}
        <tr class:quiet={!rowChanged(f)}>
          <td>
            {f.name}
            {#if f.status === "added"}<strong> {tt("fo_status_added")}</strong>{/if}
            {#if f.status === "removed"}<strong> {tt("fo_status_removed")}</strong>{/if}
          </td>
          <td class="num">
            {#if f.rows_old === f.rows_new}{f.rows_new ?? ""}{:else}
              {f.rows_old ?? "—"}→{f.rows_new ?? "—"} {delta(f.rows_old, f.rows_new)}
            {/if}
          </td>
          <td class="num">{f.row_added || ""}</td>
          <td class="num">{f.row_removed || ""}</td>
          <td class="num">{f.field_changed || ""}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

{#if overview.day_types.length}
  <h3>{tt("fo_day_types")}</h3>
  <table class="fo-table">
    <tbody>
      {#each overview.day_types as d}
        <tr class:quiet={d.old === d.new}>
          <td>{dayLabel(d.day_type)}</td>
          <td class="num">
            {#if d.old === d.new}{d.new}{:else}{d.old}→{d.new} {delta(d.old, d.new)}{/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if specials.length}
    <!-- M10: 「特定日」「運行日なし」が何を指すかを service 単位で説明する -->
    <p class="meta">{tt("fo_special_title")}:</p>
    <ul class="special-list">
      {#each specials as s}
        <li class:quiet={s.gen === "old"}>
          {s.service_id}{s.gen === "old" ? `【${tt("old_gen")}】` : ""}: {specialLine(s)}
        </li>
      {/each}
    </ul>
  {/if}
{/if}

{#if overview.calendar_view?.old || overview.calendar_view?.new}
  <!-- SD4: 運行日カレンダー (新旧並置)。記号第1チャネル (色弱原則) -->
  <h3>{tt("cal_title")}</h3>
  <p class="meta">{tt("cal_legend")}</p>
  <CalendarView view={overview.calendar_view.old} title={tt("old_gen")} />
  <CalendarView view={overview.calendar_view.new} title={tt("new_gen")} />
{/if}

<h3>{tt("fo_meta_events")}</h3>
{#if overview.meta_events.length}
  <ul>
    {#each overview.meta_events as e}
      <li><strong>{nameOf(e.type)}</strong>{detail(e) ? ` — ${detail(e)}` : ""}</li>
    {/each}
  </ul>
{:else}
  <p class="meta">{tt("fo_no_meta")}</p>
{/if}

<style>
  .fo-table { border-collapse: collapse; margin: 0.3rem 0 0.8rem; }
  .fo-table th, .fo-table td {
    border: 1px solid var(--line); padding: 0.2rem 0.55rem; text-align: left;
  }
  .fo-table .num { text-align: right; font-variant-numeric: tabular-nums; }
  tr.quiet td { color: var(--fg-soft); }
  .special-list { margin: 0.2rem 0 0.8rem 1.2rem; padding: 0; }
  .special-list li { margin: 0.15rem 0; }
  .special-list li.quiet { color: var(--fg-soft); }
  .scope-note {
    border-left: 4px solid var(--fg-soft);
    padding: 0.3rem 0.8rem; margin: 0.5rem 0 0.8rem;
  }
  .scope-note p { margin: 0 0 0.2rem; }
  .scope-note ul { margin: 0 0 0.2rem 1.2rem; padding: 0; }
</style>
