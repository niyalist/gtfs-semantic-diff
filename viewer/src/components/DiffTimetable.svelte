<script>
  import { t } from "../lib/i18n.js";
  import { fmtTime } from "../lib/format.js";

  export let table; // {label, day_type, stop_axis, columns}
  let mode = "diff"; // old | new | diff
  $: tt = $t;

  $: visibleCols = table.columns.filter((c) => {
    if (mode === "old") return c.times_old != null;
    if (mode === "new") return c.times_new != null;
    return true;
  });

  function headMark(c) {
    if (mode !== "diff") return "";
    if (c.status === "added") return tt("col_added");
    if (c.status === "removed") return tt("col_removed");
    if (c.status === "retimed" || c.status === "rerouted") return "＊";
    return "";
  }
  function cellFor(c, i) {
    // 戻り値: {text, old, cls}
    if (mode === "old") {
      return { text: fmtTime(c.times_old?.[i] ?? ""), old: null, cls: "" };
    }
    if (mode === "new") {
      return { text: fmtTime(c.times_new?.[i] ?? ""), old: null, cls: "" };
    }
    // diff
    if (c.status === "removed") {
      return { text: fmtTime(c.times_old?.[i] ?? ""), old: null, cls: "cut" };
    }
    if (c.status === "added") {
      return { text: fmtTime(c.times_new?.[i] ?? ""), old: null, cls: "new" };
    }
    const nw = c.times_new?.[i] ?? "";
    const od = c.times_old?.[i] ?? "";
    if (c.changed_positions?.includes(i)) {
      return { text: fmtTime(nw), old: fmtTime(od) || "—", cls: "chg" };
    }
    return { text: fmtTime(nw), old: null, cls: "" };
  }
</script>

<div class="tt-head">
  <span class="meta">
    {visibleCols.length} {tt("trips_count")} /
    {tt("changed_cols", table.columns.filter((c) => c.status !== "unchanged" && c.status !== "id_changed").length)}
  </span>
  <span class="mode-toggle">
    {#each ["old", "new", "diff"] as m}
      <button class:active={mode === m} on:click={() => (mode = m)}>{tt(`mode_${m}`)}</button>
    {/each}
  </span>
</div>
{#if mode === "diff"}
  <p class="note">{tt("diff_legend")}</p>
{/if}

<div class="scroll-x tt-wrap">
  <table class="tt-grid">
    <thead>
      <tr>
        <th class="stopname"></th>
        {#each visibleCols as c}
          <th class="num mark-{c.status}">{headMark(c)}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each table.stop_axis as stop, i}
        <tr>
          <th class="stopname">{stop}</th>
          {#each visibleCols as c}
            {@const cell = cellFor(c, i)}
            <td class="num cell-{cell.cls}">
              {#if cell.cls === "chg"}
                <b>{cell.text}</b><br /><s>{cell.old}</s>
              {:else if cell.cls === "cut"}
                <s>{cell.text}</s>
              {:else if cell.cls === "new"}
                <u>{cell.text}</u>
              {:else}
                {cell.text || "‥"}
              {/if}
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .tt-head { display: flex; justify-content: space-between; align-items: baseline; }
  .mode-toggle button {
    border: 1px solid var(--line); background: var(--bg);
    padding: 0.1rem 0.7rem; cursor: pointer; font-size: 0.85rem;
  }
  .mode-toggle button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .tt-wrap { max-height: 460px; overflow: auto; border: 1px solid var(--line); }
  .tt-grid { font-size: 0.78rem; border-collapse: collapse; }
  .tt-grid th.stopname {
    position: sticky; left: 0; background: var(--bg-soft); text-align: left;
    white-space: nowrap; z-index: 2; max-width: 11em; overflow: hidden;
    text-overflow: ellipsis;
  }
  .tt-grid thead th { position: sticky; top: 0; background: var(--bg-soft); z-index: 3; }
  .tt-grid td, .tt-grid th { border: 1px solid var(--line); padding: 0.1rem 0.3rem; }
  .tt-grid td { font-variant-numeric: tabular-nums; white-space: nowrap; }
  td.cell-chg { background: #fdf3d8; }   /* 補強のみ (太字+旧時刻が第1チャネル) */
  td.cell-cut s, th.mark-removed { color: #8a1c1c; }
  td.cell-new u, th.mark-added { color: #0b6e4f; }
  td.cell-cut { background: #f3ecec; }
  td.cell-new { background: #ebf3ef; }
</style>
