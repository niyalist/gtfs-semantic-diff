<script>
  import { lang, t, eventName } from "../lib/i18n.js";
  import { eventLine, subjectLabel } from "../lib/format.js";

  export let index;

  $: tt = $t;
  $: counts = (() => {
    const m = new Map();
    for (const e of index.events) {
      m.set(e.type, (m.get(e.type) || 0) + 1);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  })();
  $: majors = index.events.filter((e) => e.severity === "major");
</script>

<div class="scroll-x">
  <table>
    <thead><tr><th>{tt("event")}</th><th class="num">{tt("count")}</th></tr></thead>
    <tbody>
      {#each counts as [type, n]}
        <tr><td>{eventName(index.catalog, type, $lang)}</td><td class="num">{n}</td></tr>
      {/each}
    </tbody>
  </table>
</div>

{#if majors.length}
  <h3>{tt("major_changes")} ({majors.length})</h3>
  <div class="scroll-x">
    <table>
      <thead>
        <tr><th>{tt("type")}</th><th>{tt("target")}</th><th>{tt("description")}</th></tr>
      </thead>
      <tbody>
        {#each majors as e}
          <tr>
            <td>{eventName(index.catalog, e.type, $lang)}</td>
            <td>{subjectLabel(e, tt)}</td>
            <td>{eventLine(e, $lang)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
