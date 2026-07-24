<script>
  import { lang, t, eventName } from "../lib/i18n.js";
  import { explainerOf } from "../lib/data.js";
  import { jumpTo } from "../lib/jump.js";

  // ファイル別の生差分ブラウザ (GTFS 形式に近い軸)。
  // txt ファイル → 差分種類 → 行 (キー・カラム・旧値→新値) の順に列挙し、
  // 各行に「説明イベント → 表示先」を添える (クリックで当該レポート項目へ)。
  // 網羅性 (何も漏らさない) は件数で保証する。行の実体は core モード (Web) では
  // サンプルのみ — 全量は CLI --html か生データ DL (RD2) で (RD1a、
  // docs/design/report_delivery.md §3)。
  export let index;

  const PAGE = 100;
  const PAGE_MORE = 500;
  const KIND_ORDER = [
    "file_added", "file_removed", "column_added", "column_removed",
    "row_added", "row_removed", "field_changed",
    "rows_removed_bulk", "rows_added_bulk", "rows_changed_bulk",
  ];

  $: tt = $t;
  let residualOnly = false;
  let shown = {}; // `${file}|${kind}` → 表示件数

  $: dest = index.coverage?.destinations ?? {};
  $: files = [...index.fileDiffs.keys()].sort();

  function isResidual(d) {
    const e = explainerOf(index, d);
    return !e || e.type === "UNEXPLAINED_RESIDUAL";
  }
  function slotOf(file, kind) {
    return index.fileDiffs.get(file)?.get(kind) ?? { count: 0, rows: [] };
  }
  function rowsOf(file, kind) {
    const rows = slotOf(file, kind).rows;
    return residualOnly ? rows.filter(isResidual) : rows;
  }
  function kindsOf(file) {
    const kinds = index.fileDiffs.get(file);
    return KIND_ORDER.filter((k) => kinds?.has(k) && rowsOf(file, k).length);
  }
  function fileSummary(file) {
    const n = (k) => slotOf(file, k).count;
    const parts = [];
    if (n("row_added")) parts.push(`＋${n("row_added")}`);
    if (n("row_removed")) parts.push(`−${n("row_removed")}`);
    if (n("field_changed")) parts.push(`±${n("field_changed")}`);
    const cols = n("column_added") + n("column_removed");
    if (cols) parts.push(`${tt("fdb_columns")}${cols}`);
    if (n("file_added")) parts.push(tt("fo_status_added"));
    if (n("file_removed")) parts.push(tt("fo_status_removed"));
    return parts.join(" / ");
  }
  function destInfo(d) {
    // {label, target} — target があればクリックでレポート項目へ飛べる
    const e = explainerOf(index, d);
    if (!e) return { label: tt("fdb_unexplained"), target: null };
    const name = eventName(index.catalog, e.type, $lang);
    if (e.type === "UNEXPLAINED_RESIDUAL") return { label: name, target: null };
    const dd = dest[e.event_id];
    if (!dd) return { label: name, target: null };
    if (dd.part === 3)
      return { label: `${name} → 3. ${dd.route_group}`,
               target: { part: 3, route_group: dd.route_group } };
    return { label: `${name} → ${tt(`part${dd.part}_title`)}`,
             target: { part: dd.part } };
  }
  function more(file, kind) {
    const key = `${file}|${kind}`;
    shown = { ...shown, [key]: (shown[key] ?? PAGE) + PAGE_MORE };
  }
  function limitOf(file, kind) {
    return shown[`${file}|${kind}`] ?? PAGE;
  }
</script>

<label class="meta" style="display:block; margin: 0.3rem 0 0.5rem;">
  <input type="checkbox" bind:checked={residualOnly} />
  {tt("fdb_residual_only")}
</label>

{#each files as file (file)}
  {@const kinds = kindsOf(file)}
  {#if kinds.length}
    <details class="fdb-file">
      <summary>
        <code>{file}</code>
        <span class="count">{fileSummary(file)}</span>
      </summary>
      <div class="fdb-body">
        {#each kinds as kind (kind)}
          {@const slot = slotOf(file, kind)}
          {@const rows = rowsOf(file, kind)}
          {@const limit = limitOf(file, kind)}
          <h4>{tt(`kind_${kind}`)} <span class="count">{slot.count}</span></h4>
          <div class="scroll-x">
            <table class="fdb-table">
              <thead>
                <tr>
                  <th>{tt("key")}</th>
                  {#if kind === "field_changed" || kind.startsWith("column_")}
                    <th>{tt("column")}</th>
                  {/if}
                  {#if kind === "field_changed"}
                    <th>{tt("old_value")}</th>
                    <th>{tt("new_value")}</th>
                  {/if}
                  <th>{tt("fdb_explained_by")}</th>
                </tr>
              </thead>
              <tbody>
                {#each rows.slice(0, limit) as d (d.rawdiff_id)}
                  {@const di = destInfo(d)}
                  <tr>
                    <td><code>{d.key.join(", ")}</code></td>
                    {#if kind === "field_changed" || kind.startsWith("column_")}
                      <td><code>{d.column}</code></td>
                    {/if}
                    {#if kind === "field_changed"}
                      <td class="old">{d.old_value ?? ""}</td>
                      <td class="new">{d.new_value ?? ""}</td>
                    {/if}
                    <td class="meta">
                      {#if di.target}
                        <button class="dest-link" on:click={() => jumpTo(di.target)}>
                          {di.label}
                        </button>
                      {:else}
                        {di.label}
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
          {#if rows.length > limit}
            <button class="fdb-more" on:click={() => more(file, kind)}>
              {tt("more_rows", rows.length - limit)}
            </button>
          {:else if slot.count > rows.length && !residualOnly}
            <p class="note">{tt("fdb_sample_rest", slot.count - rows.length)}</p>
          {/if}
        {/each}
      </div>
    </details>
  {/if}
{/each}

<style>
  .fdb-file { border: 1px solid var(--line); border-radius: 4px; margin: 0.35rem 0; }
  .fdb-file > summary {
    cursor: pointer; padding: 0.35rem 0.6rem; background: var(--bg-soft);
    font-weight: 600;
  }
  .fdb-body { padding: 0.2rem 0.6rem 0.5rem; }
  .fdb-body h4 { margin: 0.6rem 0 0.2rem; }
  .fdb-table { border-collapse: collapse; }
  .fdb-table th, .fdb-table td {
    border: 1px solid var(--line); padding: 0.12rem 0.45rem;
    text-align: left; vertical-align: baseline;
  }
  .fdb-table td.old { text-decoration: line-through; color: var(--fg-soft); }
  .fdb-table td.new { font-weight: 600; }
  .fdb-more {
    margin: 0.3rem 0 0.6rem; font: inherit; cursor: pointer;
    border: 1px solid var(--line); border-radius: 4px;
    background: var(--bg-soft); padding: 0.2rem 0.7rem;
  }
  .dest-link {
    border: none; background: none; padding: 0; font: inherit;
    color: var(--accent); cursor: pointer; text-decoration: underline;
    text-align: left;
  }
</style>
