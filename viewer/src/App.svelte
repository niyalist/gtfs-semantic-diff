<script>
  import { tick } from "svelte";
  import { buildIndex } from "./lib/data.js";
  import { jumpTarget, anchorId } from "./lib/jump.js";
  import { lang, t, dayName } from "./lib/i18n.js";
  import CoverageSummary from "./components/CoverageSummary.svelte";
  import EventsByDestination from "./components/EventsByDestination.svelte";
  import FeedOverview from "./components/FeedOverview.svelte";
  import FileDiffBrowser from "./components/FileDiffBrowser.svelte";
  import RoutePage from "./components/RoutePage.svelte";
  import StopChangesPage from "./components/StopChangesPage.svelte";
  import VersionBar from "./components/VersionBar.svelte";
  import FeedbackForm from "./components/FeedbackForm.svelte";

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
  // 特定日カレンダーの描画範囲 (2026-07-29): 各世代の有効期間
  // (feed_info、無ければ実データ窓)。旧の開始〜新の終了の全期間を描くために
  // RoutePage へ渡す
  $: genWindows = (() => {
    const b = feedOverview?.data_briefs;
    if (!b) return null;
    const win = (x) => {
      if (!x) return null;
      const s = x.feed_start_date || x.window?.[0];
      const e = x.feed_end_date || x.window?.[1];
      return s && e ? [s, e] : null;
    };
    const o = win(b.old);
    const n = win(b.new);
    return o || n ? { old: o, new: n } : null;
  })();
  const catalog = bundle?.catalog ?? {};
  $: catName = (type) => catalog[type]?.[$lang === "ja" ? "ja" : "en"] ?? type;

  // 検証モードの「説明イベント → 表示先」クリックでレポート項目へ (RD1a)
  $: if ($jumpTarget) handleJump($jumpTarget);
  async function handleJump(target) {
    mode = "report";
    await tick();
    const el = document.getElementById(anchorId(target));
    if (!el) return;
    if (el.tagName === "DETAILS") el.open = true;
    // 「変更のない路線」の折りたたみ等、祖先の details も開く
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (p.tagName === "DETAILS") p.open = true;
    }
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function fmtBytes(n) {
    if (!Number.isFinite(n)) return "";
    if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
    if (n >= 1e6) return `${Math.round(n / 1e6)} MB`;
    return `${Math.max(1, Math.round(n / 1e3))} KB`;
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
    {#if agencyNames.length && feedIds}<code>{feedIds}</code> /{/if}
    {tt("old_gen")}: <code>{feed.old_rid || feed.old_source || "?"}</code>
    {#if feed.old_period?.[0]}({feed.old_period[0]} 〜 {feed.old_period[1]}){/if}
    → {tt("new_gen")}: <code>{feed.new_rid || feed.new_source || "?"}</code>
    {#if feed.new_period?.[0]}({feed.new_period[0]} 〜 {feed.new_period[1]}){/if}
    <br />
    {tt("generated")}: {index.meta?.generated_at} / {index.meta?.tool} {index.meta?.version}
    / explained_ratio {index.accounting.explained_ratio.toFixed(4)}
    {#if feed.feed_license}
      <br />
      {tt("src_line")}: <a href="https://gtfs-data.jp" target="_blank"
        rel="noopener">GTFSデータリポジトリ</a>
      <code>{feedIds}</code> — {tt("src_license")}: {feed.feed_license}
    {/if}
  </p>
  <VersionBar ownVersion={index.meta?.version || ""} />

  {#if mode === "report" && presentation}
    <p class="meta">{tt("verify_hint")}</p>

    <!-- 第1部: フィード全体の変化 -->
    {#if feedOverview}
      <h2 id="part1">{tt("part1_title")}</h2>
      <FeedOverview overview={feedOverview} {feed} {catalog} />
    {/if}

    <!-- 第2部: 停留所の変化 (地図は最初から表示) -->
    <h2 id="part2">{tt("part2_title")}</h2>
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
        <RoutePage page={p} index={`3.${i + 1}`} open={isOpen(p)} {genWindows} />
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
              <RoutePage page={p} index={`3.${changedPages.length + i + 1}`} open={false} {genWindows} />
            {/each}
          </div>
        </details>
      {/if}
    {/key}

    <!-- 第4部: その他の変化 (第1〜3部で説明していない項目 — 網羅性の受け皿) -->
    {#if feedOverview}
      <h2 id="part4">{tt("part4_title")}</h2>
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
    <!-- S3 (ui_quality.md): 表示整合セルフチェック — presentation 層の
         不変条件違反 (ヘッダ便数 vs ④時刻表列数) の台帳。explained_ratio と
         同格で常時表示する (ログにしか出ないと誰も見ない) -->
    {#if presentation?.self_check}
      <h3>{tt("selfcheck_title")}</h3>
      {#if presentation.self_check.length}
        <ul>
          {#each presentation.self_check as c}
            <li>
              {#if c.check === "level1_with_counterpart"}
                <strong>▲ {c.route_group}</strong>:
                {tt("selfcheck_counterpart",
                    c.kind === "added" ? tt("chip_new") : tt("chip_removed"),
                    [...(c.former_names ?? []), ...(c.exact_candidates ?? [])].join("、"))}
              {:else}
                <strong>▲ {c.route_group}</strong> / {dayName(c.day_type, $lang)}:
                {tt("selfcheck_line", c.header.join("→"), c.timetable.join("→"))}
                {#if c.mixed}<span class="meta">{tt("selfcheck_mixed")}</span>{/if}
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="meta">{tt("selfcheck_ok")}</p>
      {/if}
    {/if}
    {#if index.meta?.raw_urls}
      <!-- RD2: 生データ DL (検証モードのみ — レポートモードには置かない) -->
      <p class="meta">
        {tt("raw_dl_label")}:
        <a href={index.meta.raw_urls.events.url} download>
          {tt("raw_dl_events")} ({fmtBytes(index.meta.raw_urls.events.bytes)})</a>
        /
        <a href={index.meta.raw_urls.rawdiffs.url} download>
          {tt("raw_dl_rawdiffs")} ({fmtBytes(index.meta.raw_urls.rawdiffs.bytes)})</a>
      </p>
    {/if}
    <h2>{tt("dest_title")}</h2>
    <EventsByDestination {index} />
    <h2>{tt("fdb_title")}</h2>
    <p class="meta">{tt("fdb_note")}</p>
    <FileDiffBrowser {index} />
  {/if}

  <FeedbackForm ownVersion={index.meta?.version || ""} />
  <p class="note">{tt("attribution_note")}</p>
{/if}

<style>
  button.linkish {
    border: none; background: none; color: var(--accent);
    cursor: pointer; padding: 0; font-size: inherit; text-decoration: underline;
  }
</style>
