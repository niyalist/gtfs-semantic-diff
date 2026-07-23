<script>
  // SD4: 運行日カレンダービュー (docs/design/service_days.md §3)。
  // 記号が第1チャネル (色弱原則): 各日セルに「その日実際に走る世界」の1文字。
  // ▲=曜日と異なるダイヤで運行 (振替)、◆=特定日運行あり、・=運行なし。
  // 期間 (世代・季節) の切れ目は交互背景+左罫線 (補強チャネル)。
  import { lang, t } from "../lib/i18n.js";

  export let view; // {window, periods, days} | null
  export let title = "";

  $: tt = $t;

  const SYM = {
    ja: { weekday: "平", saturday: "土", sunday_holiday: "休", weekend: "週",
          daily: "毎", none: "・" },
    en: { weekday: "W", saturday: "S", sunday_holiday: "H", weekend: "E",
          daily: "D", none: "·" },
  };
  function symOf(d) {
    const m = SYM[$lang] ?? SYM.ja;
    if (!d.sym) return m.none;
    if (d.sym.startsWith("dow_")) return $lang === "en" ? "w" : "曜";
    return m[d.sym] ?? "?";
  }
  const isoDate = (s) =>
    String(s ?? "").replace(/\b(\d{4})(\d{2})(\d{2})\b/g, "$1-$2-$3");

  // 月ごとの行に分ける
  $: months = (() => {
    if (!view) return [];
    const by = new Map();
    for (const d of view.days) {
      const key = d.date.slice(0, 6);
      if (!by.has(key)) by.set(key, []);
      by.get(key).push(d);
    }
    return [...by.entries()].map(([ym, days]) => ({
      label: `${+ym.slice(0, 4)}-${ym.slice(4, 6)}`,
      pad: +days[0].date.slice(6, 8) - 1,
      days,
    }));
  })();
</script>

{#if view}
  <div class="cal">
    <p class="cal-head">
      <strong>{title}</strong>
      {isoDate(view.window[0])}〜{isoDate(view.window[1])}
      {#if view.periods.length > 1}
        / {tt("cal_periods", view.periods.map((p, i) =>
            `${"①②③④⑤⑥⑦⑧⑨⑩"[i] ?? `(${i + 1})`}${isoDate(p[0])}〜${isoDate(p[1])}`
          ).join(" "))}
      {/if}
    </p>
    <div class="scroll-x">
      <table class="cal-grid">
        <tbody>
          {#each months as m}
            <tr>
              <th>{m.label}</th>
              {#each Array(m.pad) as _}<td class="empty"></td>{/each}
              {#each m.days as d}
                <td
                  class:p-alt={d.period % 2 === 1}
                  class:p-start={d.date.slice(6, 8) !== "01" &&
                    view.periods.some((p) => p[0] === d.date)}
                  class:swap={d.swap}
                  title={`${isoDate(d.date)}: ${symOf(d)}${d.swap ? " " + tt("cal_swap") : ""}${d.special ? " " + tt("cal_special") : ""}`}
                >{d.swap ? "▲" : ""}{symOf(d)}{d.special ? "◆" : ""}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{/if}

<style>
  .cal { margin: 0.4rem 0 0.8rem; }
  .cal-head { margin: 0 0 0.2rem; }
  .cal-grid { border-collapse: collapse; font-size: 0.72rem; }
  .cal-grid th {
    text-align: right; padding: 0 0.4rem; font-weight: normal;
    color: var(--fg-soft); white-space: nowrap;
  }
  .cal-grid td {
    border: 1px solid var(--line); padding: 0 0.1rem; text-align: center;
    min-width: 1.15rem; line-height: 1.35; white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .cal-grid td.empty { border: none; }
  .cal-grid td.p-alt { background: color-mix(in srgb, var(--fg-soft) 12%, transparent); }
  .cal-grid td.p-start { border-left: 3px solid var(--fg); }
  .cal-grid td.swap { font-weight: bold; }
</style>
