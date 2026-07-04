<script>
  import EventRow from "./EventRow.svelte";

  export let index;
</script>

{#each index.stopEvents as e (e.event_id)}
  <EventRow {index} event={e} />
{/each}
