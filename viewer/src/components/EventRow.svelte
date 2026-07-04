<script>
  import { lang, t, eventName } from "../lib/i18n.js";
  import { eventLine, subjectLabel } from "../lib/format.js";
  import DetailPanel from "./DetailPanel.svelte";

  export let index;
  export let event;
  export let showSubject = true;
  export let prefix = "";

  let open = false;
  $: tt = $t;
</script>

<div
  class="event-row"
  role="button"
  tabindex="0"
  on:click={() => (open = !open)}
  on:keydown={(ev) => ev.key === "Enter" && (open = !open)}
>
  <div class="line">
    <span class="badge {event.severity}">{event.severity}</span>
    {#if prefix}<span class="meta">[{prefix}]</span>{/if}
    <span class="name">{eventName(index.catalog, event.type, $lang)}</span>
    {#if showSubject}<span class="meta">{subjectLabel(event, tt)}</span>{/if}
    <span class="summary-text">{eventLine(event, $lang)}</span>
    <span class="expander">{open ? tt("close_detail") : tt("open_detail")}</span>
  </div>
  {#if open}
    <div class="detail" on:click|stopPropagation on:keydown|stopPropagation role="group">
      <DetailPanel {index} {event} />
    </div>
  {/if}
</div>
