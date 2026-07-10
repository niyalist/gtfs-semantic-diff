<script>
  // W3-2a: 版バー。ホスト版 (/r/{pair}.html または /r/{pair}/v/{版}.html) でだけ
  // 版台帳 index.json を fetch し、自分より新しい版への案内と版セレクタを出す。
  // ローカル保存・オフライン・アップロード由来 (r/anon/) では何も表示しない。
  import { onMount } from "svelte";
  import { t } from "../lib/i18n.js";

  export let ownVersion = "";
  let info = null;
  let base = null;
  let selected = "";
  $: tt = $t;

  function baseOf(pathname) {
    let m = pathname.match(/^(\/r\/[^/]+)\/v\/[^/]+\.html$/);
    if (m) return m[1];
    m = pathname.match(/^(\/r\/[^/]+)\.html$/);
    return m ? m[1] : null;
  }

  onMount(async () => {
    try {
      base = baseOf(window.location.pathname);
      if (!base) return;
      const r = await fetch(`${base}/index.json`, { cache: "no-cache" });
      if (!r.ok) return;
      const data = await r.json();
      if (data && Array.isArray(data.versions) && data.versions.length) {
        info = data;
        selected = ownVersion;
      }
    } catch {
      /* fetch 不能 = 単一ファイル利用。バーは出さない */
    }
  });

  $: isStale = info && info.latest !== ownVersion;
  $: show = info && (isStale || info.versions.length > 1);
  const href = (v) => `${base}/v/${v}.html`;
  function onSelect() {
    if (selected && selected !== ownVersion) window.location.href = href(selected);
  }
</script>

{#if show}
  <p class="versionbar" class:stale={isStale}>
    {tt("ver_generated")}: <strong>v{ownVersion}</strong>
    {#if isStale}
      ▲ {tt("ver_newer")}: <a href={href(info.latest)}>v{info.latest}</a>
    {/if}
    {#if info.versions.length > 1}
      <label
        >{tt("ver_other")}:
        <select bind:value={selected} on:change={onSelect}>
          {#each info.versions as v (v.version)}
            <option value={v.version}>
              v{v.version} ({(v.generated_at || "").slice(0, 10)}){v.version ===
              info.latest
                ? ` ${tt("ver_latest")}`
                : ""}
            </option>
          {/each}
        </select></label
      >
    {/if}
  </p>
{/if}

<style>
  .versionbar {
    font-size: 0.85em;
    color: #444;
    border: 1px solid var(--line, #ccc);
    border-radius: 6px;
    padding: 0.3rem 0.6rem;
    background: var(--bg-soft, #f4f5f6);
  }
  /* 古い版を見ているときは記号 (▲) + 太枠が第1チャネル。色は補強のみ */
  .versionbar.stale {
    border-width: 2px;
    font-weight: 600;
  }
  select {
    font: inherit;
  }
</style>
