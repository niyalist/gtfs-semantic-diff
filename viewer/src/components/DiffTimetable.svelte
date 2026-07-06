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

  // 表示粒度 (分) で変更が残らない retimed は「変更なし」として扱う
  function effectiveStatus(c) {
    if ((c.status === "retimed" || c.status === "rerouted") && !c.changed_positions?.length) {
      return "unchanged";
    }
    return c.status;
  }
  function headMark(c) {
    if (mode !== "diff") return "";
    const st = effectiveStatus(c);
    if (st === "added") return tt("col_added");
    if (st === "removed") return tt("col_removed");
    if (st === "retimed" || st === "rerouted") return "＊";
    return "";
  }
  // 各列の表示元配列と、運行区間 (最初〜最後の経路上停留所) を求める
  function arrOf(c) {
    if (mode === "old") return c.times_old;
    if (mode === "new") return c.times_new;
    return c.status === "removed" ? c.times_old : c.times_new;
  }
  function rangeOf(arr) {
    let first = -1, last = -1;
    (arr || []).forEach((v, i) => {
      if (v !== null) {
        if (first < 0) first = i;
        last = i;
      }
    });
    return [first, last];
  }
  $: ranges = new Map(visibleCols.map((c) => [c, rangeOf(arrOf(c))]));

  function cellFor(c, i) {
    // 戻り値: {text, old, cls, sym}
    // sym: "blank"=運行区間外 / "skip"=区間内だが経由しない (＝) / "pass"=通過 (✓)
    const arr = arrOf(c);
    const v = arr?.[i] ?? null;
    if (v === null) {
      const [first, last] = ranges.get(c) ?? [-1, -1];
      const sym = first >= 0 && i > first && i < last ? "skip" : "blank";
      return { text: "", old: null, cls: "", sym };
    }
    if (v === "") return { text: "", old: null, cls: "", sym: "pass" };
    const base = { text: fmtTime(v), old: null, sym: null };
    if (mode !== "diff") return { ...base, cls: "" };
    if (c.status === "removed") return { ...base, cls: "cut" };
    if (c.status === "added") return { ...base, cls: "new" };
    if (c.changed_positions?.includes(i)) {
      const od = c.times_old?.[i];
      return { ...base, old: od ? fmtTime(od) : "—", cls: "chg" };
    }
    return { ...base, cls: "" };
  }
</script>

<div class="tt-head">
  <span class="meta">
    {visibleCols.length} {tt("trips_count")} /
    {tt("changed_cols", table.columns.filter((c) => !["unchanged", "id_changed"].includes(effectiveStatus(c))).length)}
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
              {#if cell.sym === "skip"}
                <span class="skip">‖</span>
              {:else if cell.sym === "pass"}
                <span class="skip">✓</span>
              {:else if cell.sym === "blank"}
                {""}
              {:else if cell.cls === "chg"}
                <b>{cell.text}</b><br /><s>{cell.old}</s>
              {:else if cell.cls === "cut"}
                <s>{cell.text}</s>
              {:else if cell.cls === "new"}
                <u>{cell.text}</u>
              {:else}
                {cell.text}
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
  .skip { color: var(--fg-soft); display: block; text-align: center; }
</style>
