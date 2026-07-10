<script>
  import { t } from "../lib/i18n.js";
  import EventRow from "./EventRow.svelte";

  // 全イベントを「レポートのどこに現れるか (表示先)」で分類して列挙する。
  // 第3部は route_group ごとの小見出し。各行は既存の EventRow (クリックで
  // evidence → RawDiff 生値へ到達 = 説明台帳への導線を維持)
  export let index;

  $: tt = $t;
  $: dest = index.coverage?.destinations ?? {};
  $: byPart = (() => {
    const parts = { 1: [], 2: [], 3: new Map(), 4: [] };
    for (const e of index.events) {
      const d = dest[e.event_id] ?? { part: 4, route_group: null };
      if (d.part === 3) {
        const g = d.route_group ?? "?";
        if (!parts[3].has(g)) parts[3].set(g, []);
        parts[3].get(g).push(e);
      } else {
        parts[d.part].push(e);
      }
    }
    return parts;
  })();
  $: groups3 = [...byPart[3].keys()].sort((a, b) => a.localeCompare(b, "ja"));
  $: n3 = groups3.reduce((a, g) => a + byPart[3].get(g).length, 0);
</script>

{#each [1, 2] as part}
  {#if byPart[part].length}
    <details class="dest-part">
      <summary>
        {tt(`part${part}_title`)}
        <span class="count">{byPart[part].length}</span>
      </summary>
      <div class="dest-body">
        {#each byPart[part] as e (e.event_id)}
          <EventRow {index} event={e} />
        {/each}
      </div>
    </details>
  {/if}
{/each}

{#if n3}
  <details class="dest-part">
    <summary>{tt("part3_title")} <span class="count">{n3}</span></summary>
    <div class="dest-body">
      {#each groups3 as g (g)}
        <h4>{g} <span class="count">{byPart[3].get(g).length}</span></h4>
        {#each byPart[3].get(g) as e (e.event_id)}
          <EventRow {index} event={e} />
        {/each}
      {/each}
    </div>
  </details>
{/if}

{#if byPart[4].length}
  <details class="dest-part" open>
    <summary>
      {tt("part4_title")}
      <span class="count">{byPart[4].length}</span>
      <span class="meta">— {tt("dest4_note")}</span>
    </summary>
    <div class="dest-body">
      {#each byPart[4] as e (e.event_id)}
        <EventRow {index} event={e} />
      {/each}
    </div>
  </details>
{/if}

<style>
  .dest-part { border: 1px solid var(--line); border-radius: 4px; margin: 0.4rem 0; }
  .dest-part > summary {
    cursor: pointer; padding: 0.35rem 0.6rem; background: var(--bg-soft);
    font-weight: 600;
  }
  .dest-body { padding: 0.3rem 0.6rem; }
  .dest-body h4 { margin: 0.6rem 0 0.2rem; }
</style>
