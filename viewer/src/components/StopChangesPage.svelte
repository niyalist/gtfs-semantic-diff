<script>
  import { t } from "../lib/i18n.js";
  import StopChangeMap from "./StopChangeMap.svelte";

  // 第2部の本文 (部見出しは App 側)。変化がある場合のみ描画され、
  // 地図は最初から開いた状態で出す (ユーザー要望)
  export let changes; // presentation.stop_changes

  $: tt = $t;
  $: nAdded = changes.added.reduce((a, g) => a + g.stops.length, 0);
  $: nRemoved = changes.removed.reduce((a, g) => a + g.stops.length, 0);
  $: hasGeo =
    changes.renamed.length || changes.relocated.length || nAdded || nRemoved;
  // 種別と件数の要約行 (数値+語が第1チャネル)
  $: headParts = [
    changes.renamed.length && `${tt("sc_renamed")}${changes.renamed.length}`,
    changes.relocated.length && `${tt("sc_relocated")}${changes.relocated.length}`,
    nAdded && `${tt("sc_added")}${nAdded}`,
    nRemoved && `${tt("sc_removed")}${nRemoved}`,
  ].filter(Boolean);

  function groupsLabel(gs) {
    return gs.length ? gs.join("、") : tt("sc_no_group");
  }
</script>

{#if headParts.length}
  <p><strong>{headParts.join("・")}</strong></p>
{/if}

{#if hasGeo}
  <StopChangeMap {changes} />
{/if}

{#if changes.renamed.length}
  <h3>{tt("sc_renamed")}</h3>
  <table class="sc-table">
    <tbody>
      {#each changes.renamed as r}
        <tr>
          <td><s>{r.old_name}</s> → <strong>{r.new_name}</strong></td>
          <td class="meta">{tt("sc_affected_routes")}: {groupsLabel(r.groups)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

{#if changes.relocated.length}
  <h3>{tt("sc_relocated")}</h3>
  <table class="sc-table">
    <tbody>
      {#each changes.relocated as r}
        <tr>
          <td><strong>{r.name}</strong>
            {#if r.moved_m != null}({tt("sc_moved", r.moved_m)}){/if}</td>
          <td class="meta">{tt("sc_affected_routes")}: {groupsLabel(r.groups)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

{#if nAdded}
  <h3>{tt("sc_added")} ({nAdded})</h3>
  {#each changes.added as g}
    <p class="pattern sc-bulk">
      <span class="sc-groups">{groupsLabel(g.groups)}:</span>
      {#each g.stops as s}<span class="stop added">{s.name}</span>{/each}
    </p>
  {/each}
{/if}

{#if nRemoved}
  <h3>{tt("sc_removed")} ({nRemoved})</h3>
  {#each changes.removed as g}
    <p class="pattern sc-bulk">
      <span class="sc-groups">{groupsLabel(g.groups)}:</span>
      {#each g.stops as s}<span class="stop removed">{s.name}</span>{/each}
    </p>
  {/each}
{/if}

{#if changes.platform.length}
  <!-- 乗り場の変更はマイナー扱い: 折りたたみに集約 -->
  <details class="sc-platform">
    <summary class="meta" style="cursor:pointer">
      {tt("sc_platform")} ({changes.platform.length})
    </summary>
    <ul class="meta">
      {#each changes.platform as p}
        <li>
          {p.name}:
          {#each Object.entries(p.kinds) as [kind, n], i}
            {i > 0 ? " / " : ""}{tt("sc_platform_kinds")[kind] ?? kind}{n > 1 ? ` ×${n}` : ""}
          {/each}
        </li>
      {/each}
    </ul>
  </details>
{/if}

<style>
  .sc-table { border-collapse: collapse; margin: 0.3rem 0 0.7rem; }
  .sc-table td { padding: 0.15rem 1.2rem 0.15rem 0; vertical-align: baseline; }
  .sc-bulk { margin: 0.25rem 0; }
  .sc-groups { font-weight: 600; margin-right: 0.5em; }
  .sc-platform { margin-top: 0.6rem; }
</style>
