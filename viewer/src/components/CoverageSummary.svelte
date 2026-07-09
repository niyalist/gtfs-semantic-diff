<script>
  import { lang, t, eventName } from "../lib/i18n.js";
  import EventRow from "./EventRow.svelte";

  // 網羅性ビューの先頭: 2つの被覆率と残差。
  // - RawDiff 被覆 (explained_ratio): 生差分がイベントに説明された割合 (会計の背骨)
  // - レポート被覆率: イベントがレポート第1〜3部で個別に説明される割合
  export let index;

  $: tt = $t;
  $: acc = index.accounting;
  $: cov = index.coverage;
  $: residual = index.events.filter((e) => e.type === "UNEXPLAINED_RESIDUAL");
  $: typeCounts = (() => {
    const m = new Map();
    for (const e of index.events) m.set(e.type, (m.get(e.type) || 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  })();
</script>

<table class="cov-table">
  <tbody>
    <tr>
      <td>{tt("cov_rawdiff")}</td>
      <td class="num"><strong>{acc.explained_ratio.toFixed(4)}</strong></td>
      <td class="meta">{acc.explained} / {acc.rawdiff_total} RawDiff</td>
    </tr>
    {#if cov}
      <tr>
        <td>{tt("cov_report")}</td>
        <td class="num"><strong>{cov.report_coverage_ratio.toFixed(4)}</strong></td>
        <td class="meta">
          {cov.events_total - (cov.events_by_part["4"] ?? 0)} / {cov.events_total}
          {tt("cov_events_unit")}
          ({tt("part1_title")}: {cov.events_by_part["1"] ?? 0} /
          {tt("part2_title")}: {cov.events_by_part["2"] ?? 0} /
          {tt("part3_title")}: {cov.events_by_part["3"] ?? 0} /
          {tt("part4_title")}: {cov.events_by_part["4"] ?? 0})
        </td>
      </tr>
      {#if cov.lev1_trip_ratio != null}
        <!-- M9 (I3): family 対応の取りこぼし (改称・再編の見逃し) の煙感知器 -->
        <tr>
          <td>{tt("cov_lev1")}</td>
          <td class="num"><strong>{cov.lev1_trip_ratio.toFixed(4)}</strong></td>
          <td class="meta">{tt("cov_lev1_note")}</td>
        </tr>
      {/if}
    {/if}
  </tbody>
</table>

<h3>{tt("residual_all")}</h3>
{#if residual.length}
  {#each residual as e (e.event_id)}
    <EventRow {index} event={e} />
  {/each}
{:else}
  <p class="note">{tt("no_residual")}</p>
{/if}

<details>
  <summary class="meta" style="cursor:pointer">{tt("cov_type_counts")}</summary>
  <div class="scroll-x">
    <table>
      <thead><tr><th>{tt("event")}</th><th class="num">{tt("count")}</th></tr></thead>
      <tbody>
        {#each typeCounts as [type, n]}
          <tr><td>{eventName(index.catalog, type, $lang)}</td><td class="num">{n}</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</details>

<style>
  .cov-table { border-collapse: collapse; margin: 0.4rem 0 0.8rem; }
  .cov-table td { padding: 0.2rem 0.9rem 0.2rem 0; vertical-align: baseline; }
  .cov-table .num { font-size: 1.15em; }
</style>
