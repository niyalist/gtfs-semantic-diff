<script>
  import { lang, t } from "../lib/i18n.js";

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
  // フィード級イベントの読み下し: 旧→新の値があればそれを、なければ数値詳細を添える
  function detail(e) {
    const o = e.old_ref || {}, n = e.new_ref || {};
    const parts = [];
    for (const k of Object.keys({ ...o, ...n })) {
      if (o[k] !== undefined || n[k] !== undefined)
        parts.push(`${o[k] ?? "—"} → ${n[k] ?? "—"}`);
    }
    if (!parts.length && e.quantification) {
      for (const [k, v] of Object.entries(e.quantification))
        parts.push(`${k}: ${Array.isArray(v) ? v.join(", ") : v}`);
    }
    const subj = Object.values(e.subject || {}).join(" ");
    return [subj, parts.join(" / ")].filter(Boolean).join(" — ");
  }
</script>

{#if feed.old_period?.[0] || feed.new_period?.[0]}
  <p>
    <strong>{tt("fo_period")}</strong>:
    {feed.old_period?.[0] ?? "?"} 〜 {feed.old_period?.[1] ?? "?"}
    → {feed.new_period?.[0] ?? "?"} 〜 {feed.new_period?.[1] ?? "?"}
  </p>
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
          <td>{tt(d.day_type) === d.day_type ? d.day_type : tt(d.day_type)}</td>
          <td class="num">
            {#if d.old === d.new}{d.new}{:else}{d.old}→{d.new} {delta(d.old, d.new)}{/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
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
</style>
