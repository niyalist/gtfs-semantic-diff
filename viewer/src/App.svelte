<script>
  import { buildIndex } from "./lib/data.js";
  import { lang, t } from "./lib/i18n.js";
  import Summary from "./components/Summary.svelte";
  import RouteChapters from "./components/RouteChapters.svelte";
  import StopsChapter from "./components/StopsChapter.svelte";
  import Validation from "./components/Validation.svelte";

  export let bundle = null;
  const index = bundle ? buildIndex(bundle) : null;

  $: tt = $t;
  const feed = index?.feed || {};
  const title = [feed.org_id, feed.feed_id].filter(Boolean).join(" / ");
</script>

{#if !index}
  <p>{tt("no_data")}</p>
{:else}
  <div class="lang-toggle">
    <button class:active={$lang === "ja"} on:click={() => lang.set("ja")}>日本語</button>
    <button class:active={$lang === "en"} on:click={() => lang.set("en")}>EN</button>
  </div>
  <h1>{tt("title")}{title ? `: ${title}` : ""}</h1>
  <p class="meta">
    {tt("old_gen")}: <code>{feed.old_rid || feed.old_source || "?"}</code>
    {#if feed.old_period?.[0]}({feed.old_period[0]}〜 {feed.old_period[1]}){/if}
    → {tt("new_gen")}: <code>{feed.new_rid || feed.new_source || "?"}</code>
    {#if feed.new_period?.[0]}({feed.new_period[0]} 〜 {feed.new_period[1]}){/if}
    <br />
    {tt("generated")}: {index.meta?.generated_at} / {index.meta?.tool} {index.meta?.version}
    / schema {bundle.events.schema_version}
  </p>

  <h2>{tt("summary")}</h2>
  <Summary {index} />

  <h2>{tt("routes")}</h2>
  <RouteChapters {index} />

  {#if index.stopEvents.length}
    <h2>{tt("stops")}</h2>
    <StopsChapter {index} />
  {/if}

  <h2>{tt("validation")}</h2>
  <Validation {index} />

  <p class="note">{tt("attribution_note")}</p>
{/if}
