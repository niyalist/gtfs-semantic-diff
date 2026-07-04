<script>
  import { t } from "../lib/i18n.js";

  export let oldPattern = [];
  export let newPattern = [];

  $: tt = $t;
  $: oldSet = new Set(oldPattern);
  $: newSet = new Set(newPattern);
</script>

<div>
  <div class="meta">{tt("old")}:</div>
  <div class="pattern">
    {#each oldPattern as stop, i}
      {#if i > 0}<span class="arrow">→</span>{/if}
      <span class="stop" class:removed={!newSet.has(stop)}>{stop}</span>
    {/each}
  </div>
  <div class="meta" style="margin-top:0.4rem">{tt("new")}:</div>
  <div class="pattern">
    {#each newPattern as stop, i}
      {#if i > 0}<span class="arrow">→</span>{/if}
      <span class="stop" class:added={!oldSet.has(stop)}>{stop}</span>
    {/each}
  </div>
</div>
