<script>
  // SD4: 運行日カレンダービュー (docs/design/service_days.md §3)。
  // 月ごとのミニカレンダー (月曜始まり7列) を横に並べ、幅で折り返す
  // (最大4ヶ月/行)。セル = 日付数字 (小・薄) + その日走る世界の記号。
  // 記号が第1チャネル (色弱原則): ▲=曜日と異なるダイヤ (振替)、◆=特定日
  // 運行あり、・=運行なし。期間 (世代・季節) の切れ目は交互背景+太罫線 (補強)。
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
  const DOW_HEAD = {
    ja: ["月", "火", "水", "木", "金", "土", "日"],
    en: ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
  };
  function symOf(d) {
    const m = SYM[$lang] ?? SYM.ja;
    if (!d.sym) return m.none;
    if (d.sym.startsWith("dow_")) return $lang === "en" ? "w" : "曜";
    return m[d.sym] ?? "?";
  }
  const isoDate = (s) =>
    String(s ?? "").replace(/\b(\d{4})(\d{2})(\d{2})\b/g, "$1-$2-$3");
  // 月曜始まりの列位置 (0=月 … 6=日)
  const mondayCol = (ymd) =>
    (new Date(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8)).getDay() + 6) % 7;

  // 月ごとに週 (7日×n行) へ整形。月は必ず1日〜末日までフルに敷き、
  // 窓外の日は {out:true} (薄い日付数字のみ) で埋める
  $: months = (() => {
    if (!view) return [];
    const by = new Map();
    for (const d of view.days) {
      const key = d.date.slice(0, 6);
      if (!by.has(key)) by.set(key, new Map());
      by.get(key).set(+d.date.slice(6, 8), d);
    }
    return [...by.entries()].map(([ym, dayMap]) => {
      const y = +ym.slice(0, 4);
      const mo = +ym.slice(4, 6);
      const lastDay = new Date(y, mo, 0).getDate();
      const cells = [];
      const first = `${ym}01`;
      for (let i = 0; i < mondayCol(first); i++) cells.push(null);
      for (let day = 1; day <= lastDay; day++) {
        const date = `${ym}${String(day).padStart(2, "0")}`;
        cells.push(dayMap.get(day) ?? { date, out: true });
      }
      while (cells.length % 7) cells.push(null);
      const weeks = [];
      for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
      return { label: `${y}-${ym.slice(4, 6)}`, weeks };
    });
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
    <div class="cal-months">
      {#each months as m}
        <table class="cal-month">
          <thead>
            <tr><th colspan="7" class="mon">{m.label}</th></tr>
            <tr>
              {#each DOW_HEAD[$lang] ?? DOW_HEAD.ja as h}
                <th class="dow">{h}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each m.weeks as w}
              <tr>
                {#each w as d}
                  {#if d && !d.out}
                    <td
                      class:p-alt={d.period % 2 === 1}
                      class:p-start={view.periods.length > 1 &&
                        view.periods.some((p) => p[0] === d.date)}
                      class:swap={d.swap}
                      title={`${isoDate(d.date)}: ${symOf(d)}${d.swap ? " " + tt("cal_swap") : ""}${d.special ? " " + tt("cal_special") : ""}`}
                    >
                      <span class="dn">{+d.date.slice(6, 8)}{d.special ? "◆" : ""}</span>
                      <span class="sy">{d.swap ? "▲" : ""}{symOf(d)}</span>
                    </td>
                  {:else if d}
                    <!-- 窓外の日: 月の形を保つため薄い日付だけ置く -->
                    <td class="out"><span class="dn">{+d.date.slice(6, 8)}</span></td>
                  {:else}
                    <td class="empty"></td>
                  {/if}
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      {/each}
    </div>
  </div>
{/if}

<style>
  /* 幾何は固定 (内容に依らない): セル 1.5rem × 7列 = 月 10.5rem、常に4ヶ月/行。
     新旧カレンダーで大きさ・縦位置が必ず揃う。カレンダーは補助情報なので
     主張は抑える (細罫線・小さめの字) */
  .cal { margin: 0.3rem 0 0.7rem; }
  .cal-head { margin: 0 0 0.25rem; font-size: 0.85rem; }
  .cal-months {
    display: flex; flex-wrap: wrap; gap: 0.5rem 0.8rem;
    align-items: flex-start;
    max-width: 45rem; /* 4ヶ月 (10.5rem×4 + gap×3) で必ず折り返す */
  }
  /* app.css の table { width: 100% } を打ち消し + 内容非依存の固定レイアウト */
  .cal-month {
    border-collapse: collapse; table-layout: fixed;
    width: 10.5rem; flex: 0 0 auto;
  }
  .cal-month th.mon {
    text-align: left; font-weight: 600; font-size: 0.68rem;
    color: var(--fg-soft); padding: 0 0 0.1rem 0.05rem;
  }
  .cal-month th.dow {
    font-weight: normal; font-size: 0.5rem; color: var(--fg-soft);
    text-align: center; padding: 0;
  }
  .cal-month td {
    border: 1px solid color-mix(in srgb, var(--line) 60%, transparent);
    height: 2.15rem; overflow: hidden;
    padding: 0.14rem 0.02rem 0.06rem; text-align: center; vertical-align: top;
  }
  .cal-month td.empty { border: none; }
  .cal-month td.out {
    border: 1px solid color-mix(in srgb, var(--line) 30%, transparent);
  }
  .cal-month td.out .dn { opacity: 0.45; }
  .cal-month td .dn {
    display: block; font-size: 0.52rem; line-height: 1.1;
    color: var(--fg-soft); font-variant-numeric: tabular-nums;
    white-space: nowrap; margin-bottom: 0.12rem;
  }
  .cal-month td .sy {
    display: block; font-size: 0.7rem; line-height: 1.2; white-space: nowrap;
  }
  .cal-month td.p-alt { background: color-mix(in srgb, var(--fg-soft) 13%, transparent); }
  .cal-month td.p-start { border: 2px solid var(--fg); }
  .cal-month td.swap .sy { font-weight: bold; }
</style>
