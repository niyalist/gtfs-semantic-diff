<script>
  import { buildIndex } from "./lib/data.js";
  import { lang, t } from "./lib/i18n.js";
  import RoutePage from "./components/RoutePage.svelte";
  import StopChangesPage from "./components/StopChangesPage.svelte";
  import Summary from "./components/Summary.svelte";
  import RouteChapters from "./components/RouteChapters.svelte";
  import StopsChapter from "./components/StopsChapter.svelte";
  import Validation from "./components/Validation.svelte";

  export let bundle = null;
  const index = bundle ? buildIndex(bundle) : null;
  const presentation = bundle?.presentation;

  let mode = "report"; // report | verify
  let expandState = null; // null=既定 / "open" / "closed"

  $: tt = $t;
  const feed = index?.feed || {};
  const title = [feed.org_id, feed.feed_id].filter(Boolean).join(" / ");

  $: pages = presentation?.route_pages ?? [];
  $: changedPages = pages.filter((p) => p.has_changes);
  $: unchangedPages = pages.filter((p) => !p.has_changes);
  $: stopChanges = presentation?.stop_changes;
  $: hasStopChanges = Boolean(
    stopChanges &&
    (stopChanges.renamed.length || stopChanges.relocated.length ||
     stopChanges.added.length || stopChanges.removed.length ||
     stopChanges.platform.length)
  );
  function stopChapterOpen() {
    if (expandState === "open") return true;
    if (expandState === "closed") return false;
    // 改称・移設は重要なので既定で展開。新設・廃止のみ (路線側で説明済みが
    // 多い) や乗り場のみなら折りたたみ
    return Boolean(stopChanges?.renamed.length || stopChanges?.relocated.length);
  }

  function defaultOpen(p) {
    // 既定の折りたたみ戦略: Lev.1/Lev.2 を含むページのみ展開 (大規模改正対策)
    return Boolean(p.summary.level1 || p.summary.level2.length);
  }
  function isOpen(p) {
    if (expandState === "open") return true;
    if (expandState === "closed") return false;
    return defaultOpen(p);
  }
</script>

{#if !index}
  <p>{tt("no_data")}</p>
{:else}
  <div class="lang-toggle">
    <button class:active={mode === "report"} on:click={() => (mode = "report")}>
      {tt("mode_normal")}
    </button>
    <button class:active={mode === "verify"} on:click={() => (mode = "verify")}>
      {tt("mode_verify")}
    </button>
    &nbsp;
    <button class:active={$lang === "ja"} on:click={() => lang.set("ja")}>日本語</button>
    <button class:active={$lang === "en"} on:click={() => lang.set("en")}>EN</button>
  </div>
  <h1>{tt("title")}{title ? `: ${title}` : ""}</h1>
  <p class="meta">
    {tt("old_gen")}: <code>{feed.old_rid || feed.old_source || "?"}</code>
    {#if feed.old_period?.[0]}({feed.old_period[0]} 〜 {feed.old_period[1]}){/if}
    → {tt("new_gen")}: <code>{feed.new_rid || feed.new_source || "?"}</code>
    {#if feed.new_period?.[0]}({feed.new_period[0]} 〜 {feed.new_period[1]}){/if}
    <br />
    {tt("generated")}: {index.meta?.generated_at} / {index.meta?.tool} {index.meta?.version}
    / explained_ratio {index.accounting.explained_ratio.toFixed(4)}
  </p>

  {#if mode === "report" && presentation}
    <p class="meta">
      {tt("verify_hint")}
      <span style="float:right">
        <button class="linkish" on:click={() => (expandState = "open")}>{tt("expand_all")}</button>
        /
        <button class="linkish" on:click={() => (expandState = "closed")}>{tt("collapse_all")}</button>
      </span>
    </p>
    {#key expandState}
      {#each changedPages as p, i (p.route_group)}
        <RoutePage page={p} index={i + 1} open={isOpen(p)} />
      {/each}
      {#if hasStopChanges}
        <StopChangesPage changes={stopChanges} index={changedPages.length + 1}
                         open={stopChapterOpen()} />
      {/if}
      {#if unchangedPages.length}
        <details class="chapter">
          <summary>
            {tt("unchanged_routes")}
            <span class="count">{unchangedPages.length}</span>
          </summary>
          <div class="body">
            <p class="note">{tt("unchanged_note")}</p>
            {#each unchangedPages as p, i (p.route_group)}
              <RoutePage page={p} index={changedPages.length + hasStopChanges + i + 1} open={false} />
            {/each}
          </div>
        </details>
      {/if}
    {/key}
  {:else}
    <!-- 検証モード: W1 のイベント単位 UI (説明会計への導線を維持) -->
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
  {/if}

  <p class="note">{tt("attribution_note")}</p>
{/if}

<style>
  button.linkish {
    border: none; background: none; color: var(--accent);
    cursor: pointer; padding: 0; font-size: inherit; text-decoration: underline;
  }
</style>
