<script>
  import { t } from "../lib/i18n.js";
  import EventRow from "./EventRow.svelte";

  export let index;

  $: tt = $t;
  $: acc = index.accounting;
  $: churn = index.validationEvents.filter((e) => e.type === "TECHNICAL_ID_CHURN");
  $: validity = index.validationEvents.filter((e) => e.type === "FEED_VALIDITY_CHANGED");
  $: residual = index.validationEvents.filter((e) => e.type === "UNEXPLAINED_RESIDUAL");
  $: others = index.feedEvents; // FARE / AGENCY / TRANSLATION / DAYTYPE / HOLIDAY / DEMAND 等
</script>

<p>
  {tt("explained_ratio")}: <strong>{acc.explained_ratio.toFixed(4)}</strong>
  ({acc.explained} / {acc.rawdiff_total} RawDiff)
</p>

{#each others as e (e.event_id)}
  <EventRow {index} event={e} />
{/each}

{#if churn.length}
  <h3>{tt("id_churn")}</h3>
  {#each churn as e (e.event_id)}
    <EventRow {index} event={e} />
  {/each}
{/if}

{#each validity as e (e.event_id)}
  <EventRow {index} event={e} />
{/each}

<h3>{tt("residual_all")}</h3>
{#if residual.length}
  {#each residual as e (e.event_id)}
    <EventRow {index} event={e} />
  {/each}
{:else}
  <p class="note">{tt("no_residual")}</p>
{/if}
