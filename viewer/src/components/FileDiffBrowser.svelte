<script>
  import { lang, t, eventName } from "../lib/i18n.js";

  // ファイル別の生差分ブラウザ (GTFS 形式に近い軸)。
  // txt ファイル → 差分種類 → 行 (キー・カラム・旧値→新値) の順に全 RawDiff を
  // 列挙し、各行に「説明イベント → 表示先」を添える。件数が多いテーブルは
  // 段階表示 (もっと見る)。網羅性の確認が目的なので何も省かない。
  export let index;

  const PAGE = 100;
  const PAGE_MORE = 500;
  const KIND_ORDER = [
    "file_added", "file_removed", "column_added", "column_removed",
    "row_added", "row_removed", "field_changed",
  ];

  $: tt = $t;
  let residualOnly = false;
  let shown = {}; // `${file}|${kind}` → 表示件数

  $: dest = index.coverage?.destinations ?? {};
  $: files = [...index.rawdiffsByFile.keys()].sort();

  function isResidual(d) {
    const e = index.explainerByRawdiff.get(d.rawdiff_id);
    return !e || e.type === "UNEXPLAINED_RESIDUAL";
  }
  function rowsOf(file, kind) {
    const all = index.rawdiffsByFile.get(file)?.get(kind) ?? [];
    return residualOnly ? all.filter(isResidual) : all;
  }
  function kindsOf(file) {
    const kinds = index.rawdiffsByFile.get(file);
    return KIND_ORDER.filter((k) => kinds?.has(k) && rowsOf(file, k).length);
  }
  function fileSummary(file) {
    const kinds = index.rawdiffsByFile.get(file);
    const n = (k) => kinds?.get(k)?.length ?? 0;
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
  function destLabel(d) {
    const e = index.explainerByRawdiff.get(d.rawdiff_id);
    if (!e) return tt("fdb_unexplained");
    const name = eventName(index.catalog, e.type, $lang);
    if (e.type === "UNEXPLAINED_RESIDUAL") return name;
    const dd = dest[e.event_id];
    if (!dd) return name;
    if (dd.part === 3) return `${name} → 3. ${dd.route_group}`;
    return `${name} → ${tt(`part${dd.part}_title`)}`;
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
          {@const rows = rowsOf(file, kind)}
          {@const limit = limitOf(file, kind)}
          <h4>{tt(`kind_${kind}`)} <span class="count">{rows.length}</span></h4>
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
                  <tr>
                    <td><code>{d.key.join(", ")}</code></td>
                    {#if kind === "field_changed" || kind.startsWith("column_")}
                      <td><code>{d.column}</code></td>
                    {/if}
                    {#if kind === "field_changed"}
                      <td class="old">{d.old_value ?? ""}</td>
                      <td class="new">{d.new_value ?? ""}</td>
                    {/if}
                    <td class="meta">{destLabel(d)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
          {#if rows.length > limit}
            <button class="fdb-more" on:click={() => more(file, kind)}>
              {tt("more_rows", rows.length - limit)}
            </button>
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
</style>
