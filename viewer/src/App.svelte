<script>
  import { buildIndex } from "./lib/data.js";
  import { lang, t } from "./lib/i18n.js";
  import CoverageSummary from "./components/CoverageSummary.svelte";
  import EventsByDestination from "./components/EventsByDestination.svelte";
  import FeedOverview from "./components/FeedOverview.svelte";
  import FileDiffBrowser from "./components/FileDiffBrowser.svelte";
  import RoutePage from "./components/RoutePage.svelte";
  import StopChangesPage from "./components/StopChangesPage.svelte";
  import VersionBar from "./components/VersionBar.svelte";

  export let bundle = null;
  const index = bundle ? buildIndex(bundle) : null;
  const presentation = bundle?.presentation;

  let mode = "report"; // report | verify
  let expandState = null; // null=既定 / "open" / "closed"

  $: tt = $t;
  const feed = index?.feed || {};
  const feedIds = [feed.org_id, feed.feed_id].filter(Boolean).join(" / ");
  // 表題は GTFS の agency_name (無ければ gtfs-data.jp の org/feed ID にフォールバック)
  const agencyNames = index?.meta?.agency_names ?? [];
  const title = agencyNames.length ? agencyNames.join("・") : feedIds;

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
  $: feedOverview = presentation?.feed_overview;
  const catalog = bundle?.catalog ?? {};
  $: catName = (type) => catalog[type]?.[$lang === "ja" ? "ja" : "en"] ?? type;

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
    {#if agencyNames.length && feedIds}<code>{feedIds}</code> /{/if}
    {tt("old_gen")}: <code>{feed.old_rid || feed.old_source || "?"}</code>
    {#if feed.old_period?.[0]}({feed.old_period[0]} 〜 {feed.old_period[1]}){/if}
    → {tt("new_gen")}: <code>{feed.new_rid || feed.new_source || "?"}</code>
    {#if feed.new_period?.[0]}({feed.new_period[0]} 〜 {feed.new_period[1]}){/if}
    <br />
    {tt("generated")}: {index.meta?.generated_at} / {index.meta?.tool} {index.meta?.version}
    / explained_ratio {index.accounting.explained_ratio.toFixed(4)}
  </p>
  <VersionBar ownVersion={index.meta?.version || ""} />

  {#if mode === "report" && presentation}
    <p class="meta">{tt("verify_hint")}</p>

    <!-- 第1部: フィード全体の変化 -->
    {#if feedOverview}
      <h2>{tt("part1_title")}</h2>
      <FeedOverview overview={feedOverview} {feed} {catalog} />
    {/if}

    <!-- 第2部: 停留所の変化 (地図は最初から表示) -->
    <h2>{tt("part2_title")}</h2>
    {#if hasStopChanges}
      <StopChangesPage changes={stopChanges} />
    {:else}
      <p class="meta">{tt("sc_none")}</p>
    {/if}

    <!-- 第3部: 路線毎の変化 (変更のない路線も含む) -->
    <h2>
      {tt("part3_title")}
      <span style="float:right; font-size: 0.7em; font-weight: normal">
        <button class="linkish" on:click={() => (expandState = "open")}>{tt("expand_all")}</button>
        /
        <button class="linkish" on:click={() => (expandState = "closed")}>{tt("collapse_all")}</button>
      </span>
    </h2>
    {#key expandState}
      {#each changedPages as p, i (p.route_group)}
        <RoutePage page={p} index={`3.${i + 1}`} open={isOpen(p)} />
      {/each}
      {#if unchangedPages.length}
        <details class="chapter">
          <summary>
            {tt("unchanged_routes")}
            <span class="count">{unchangedPages.length}</span>
          </summary>
          <div class="body">
            <p class="note">{tt("unchanged_note")}</p>
            {#each unchangedPages as p, i (p.route_group)}
              <RoutePage page={p} index={`3.${changedPages.length + i + 1}`} open={false} />
            {/each}
          </div>
        </details>
      {/if}
    {/key}

    <!-- 第4部: その他の変化 (第1〜3部で説明していない項目 — 網羅性の受け皿) -->
    {#if feedOverview}
      <h2>{tt("part4_title")}</h2>
      {#if feedOverview.others.length}
        <p class="meta">{tt("part4_note")}</p>
        <ul>
          {#each feedOverview.others as o}
            <li><strong>{catName(o.type)}</strong>: {tt("count_unit", o.count)}</li>
          {/each}
        </ul>
      {:else}
        <p class="meta">{tt("part4_none")}</p>
      {/if}
    {/if}
  {:else}
    <!-- 検証モード = 網羅性ビュー (V5): 台帳サマリー → イベント (表示先別) →
         ファイル別の生差分。EventRow のドリルダウンで evidence → RawDiff 生値へ
         到達できる (説明台帳への導線を維持) -->
    <h2>{tt("cov_title")}</h2>
    <CoverageSummary {index} />
    <h2>{tt("dest_title")}</h2>
    <EventsByDestination {index} />
    <h2>{tt("fdb_title")}</h2>
    <p class="meta">{tt("fdb_note")}</p>
    <FileDiffBrowser {index} />
  {/if}

  <p class="note">{tt("attribution_note")}</p>
{/if}

<style>
  button.linkish {
    border: none; background: none; color: var(--accent);
    cursor: pointer; padding: 0; font-size: inherit; text-decoration: underline;
  }
</style>
