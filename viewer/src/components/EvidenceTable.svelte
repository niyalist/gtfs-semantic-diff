<script>
  import { t } from "../lib/i18n.js";

  export let index;
  export let ids = [];       // full モード: rawdiff ID 列から引く
  export let sample = null;  // core モード: 焼き込み済みサンプル行
  export let total = null;   // core モード: 全件数

  const LIMIT = 300;
  $: tt = $t;
  $: rows = sample
    ? sample
    : ids.slice(0, LIMIT).map((id) => index.rawdiffById.get(id)).filter(Boolean);
  $: all = total ?? ids.length;
  $: rest = all - Math.min(all, rows.length);
</script>

<div class="scroll-x">
  <table>
    <thead>
      <tr>
        <th>{tt("file")}</th>
        <th>{tt("kind")}</th>
        <th>{tt("key")}</th>
        <th>{tt("column")}</th>
        <th>{tt("old_value")}</th>
        <th>{tt("new_value")}</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as d}
        <tr>
          <td>{d.file}</td>
          <td>{d.kind}</td>
          <td>{(d.key || []).join(" / ")}</td>
          <td>{d.column || ""}</td>
          <td>{d.old_value ?? ""}</td>
          <td>{d.new_value ?? ""}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
{#if rest > 0}
  <p class="note">{tt("more_rows", rest)}</p>
{/if}
