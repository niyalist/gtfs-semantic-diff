<script>
  // W3-2c: 問題報告フォーム。ホスト版 (/r/…) でだけ表示し、報告には版固定 URL を
  // 記録する (結果は不変保存なので報告は常に再現・検証可能 — web.md の原則)。
  import { onMount } from "svelte";
  import { t } from "../lib/i18n.js";

  export let ownVersion = "";
  let hosted = false;
  let message = "";
  let eventId = "";
  let state = "idle"; // idle | sending | done | error
  let errorMsg = "";
  $: tt = $t;

  function pinnedUrl() {
    const p = window.location.pathname;
    // 入口 (r/{pair}.html) からの報告は生成版の固定 URL に付け替える
    const m = p.match(/^(\/r\/[^/]+)\.html$/);
    if (m && ownVersion && !p.startsWith("/r/anon/") && !p.startsWith("/r/u/")) {
      return `${m[1]}/v/${ownVersion}.html`;
    }
    return p;
  }

  onMount(() => {
    hosted = window.location.pathname.startsWith("/r/");
  });

  async function send() {
    state = "sending";
    try {
      const r = await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          message,
          event_id: eventId,
          result_url: pinnedUrl(),
        }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
      state = "done";
    } catch (e) {
      errorMsg = e.message;
      state = "error";
    }
  }
</script>

{#if hosted}
  <details class="fb">
    <summary>{tt("fb_report")}</summary>
    {#if state === "done"}
      <p>{tt("fb_thanks")}</p>
    {:else}
      <p class="hint">{tt("fb_hint")}</p>
      <textarea rows="4" bind:value={message} placeholder={tt("fb_placeholder")}
      ></textarea>
      <label
        >{tt("fb_event_id")}:
        <input type="text" bind:value={eventId} placeholder="evt_x00123" /></label
      >
      <div>
        <button on:click={send} disabled={!message.trim() || state === "sending"}>
          {state === "sending" ? "…" : tt("fb_send")}
        </button>
        {#if state === "error"}<span class="err">▲ {errorMsg}</span>{/if}
      </div>
    {/if}
  </details>
{/if}

<style>
  .fb {
    margin: 1.2rem 0;
    border: 1px solid var(--line, #ccc);
    border-radius: 6px;
    padding: 0.4rem 0.7rem;
    font-size: 0.9em;
  }
  .fb summary {
    cursor: pointer;
    font-weight: 600;
  }
  textarea {
    width: 100%;
    font: inherit;
    box-sizing: border-box;
  }
  input {
    font: inherit;
  }
  button {
    font: inherit;
    cursor: pointer;
    margin-top: 0.3rem;
  }
  .hint {
    color: #555;
    font-size: 0.9em;
    margin: 0.3rem 0;
  }
  .err {
    font-weight: 700;
  }
</style>
