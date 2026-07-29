<script>
  // 特定日運行日のコンパクトカレンダー (2026-07-29 ユーザー仕様)。
  // 月ごとに日曜始まり 7列×5-6行、横に最大6ヶ月で折返し。対象の全日付を含む
  // (「ほかN区間」の省略はしない)。1つのカレンダーに旧/新の両方を塗り、
  // 旧のみ=取り消し線・新のみ=下線・両方=塗りつぶし — ④時刻表の差分表示と
  // 同じ記号語彙 (取り消し=なくなる/下線=新設) を第1チャネルに、色は補強
  // (色弱原則)。
  import { lang, t } from "../lib/i18n.js";

  export let oldRuns = [];
  export let newRuns = [];

  $: tt = $t;
  const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const WD = { ja: ["日", "月", "火", "水", "木", "金", "土"],
               en: ["S", "M", "T", "W", "T", "F", "S"] };

  function expand(runs) {
    const s = new Set();
    for (const [a, b] of runs ?? []) {
      let d = new Date(+a.slice(0, 4), +a.slice(4, 6) - 1, +a.slice(6, 8));
      const end = new Date(+b.slice(0, 4), +b.slice(4, 6) - 1, +b.slice(6, 8));
      while (d <= end) {
        s.add(`${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`);
        d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1);
      }
    }
    return s;
  }
  $: oldSet = expand(oldRuns);
  $: newSet = expand(newRuns);

  function buildWeeks(y, m) {
    const startCol = new Date(y, m - 1, 1).getDay(); // 0=日曜
    const daysIn = new Date(y, m, 0).getDate();
    const cells = Array(startCol).fill(null);
    for (let d = 1; d <= daysIn; d++) cells.push(d);
    while (cells.length % 7) cells.push(null);
    const weeks = [];
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
    return weeks;
  }
  $: months = (() => {
    const all = [...oldSet, ...newSet].sort();
    if (!all.length) return [];
    let y = +all[0].slice(0, 4);
    let m = +all[0].slice(4, 6);
    const last = all[all.length - 1];
    const endY = +last.slice(0, 4);
    const endM = +last.slice(4, 6);
    const out = [];
    while (y < endY || (y === endY && m <= endM)) {
      out.push({ y, m, weeks: buildWeeks(y, m) });
      m += 1;
      if (m > 12) { m = 1; y += 1; }
    }
    return out;
  })();
  function cls(y, m, d) {
    const k = `${y}${String(m).padStart(2, "0")}${String(d).padStart(2, "0")}`;
    const o = oldSet.has(k);
    const n = newSet.has(k);
    return o && n ? "both" : o ? "old" : n ? "new" : "";
  }
  function monthLabel(y, m) {
    return $lang === "en" ? `${MONTHS_EN[m - 1]} ${y}` : `${y}年${m}月`;
  }
</script>

<div class="scroll-x">
  <div class="cal-strip">
    {#each months as mo}
      <table class="cal-month">
        <caption>{monthLabel(mo.y, mo.m)}</caption>
        <thead>
          <tr>{#each WD[$lang === "en" ? "en" : "ja"] as w}<th>{w}</th>{/each}</tr>
        </thead>
        <tbody>
          {#each mo.weeks as week}
            <tr>
              {#each week as d}
                {#if d === null}
                  <td></td>
                {:else}
                  {@const c = cls(mo.y, mo.m, d)}
                  <td class={c}>
                    {#if c === "old"}<s>{d}</s>
                    {:else if c === "new"}<u>{d}</u>
                    {:else}{d}{/if}
                  </td>
                {/if}
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    {/each}
  </div>
</div>
<p class="cal-legend">
  {#if oldSet.size && newSet.size}
    <span class="chip both">15</span> {tt("cal_both")}
    ／ <span class="chip old"><s>15</s></span> {tt("cal_old_only")}
    ／ <span class="chip new"><u>15</u></span> {tt("cal_new_only")}
  {:else if oldSet.size}
    <span class="chip old"><s>15</s></span> {tt("cal_old_side")}
  {:else}
    <span class="chip new"><u>15</u></span> {tt("cal_new_side")}
  {/if}
</p>

<style>
  .cal-strip {
    display: grid;
    /* 横に最大6ヶ月、超えたら折返し (ユーザー仕様) */
    grid-template-columns: repeat(6, max-content);
    gap: 0.5rem 0.9rem;
    margin: 0.35rem 0 0.1rem;
    width: max-content;
  }
  .cal-month { border-collapse: collapse; }
  .cal-month caption {
    font-size: 0.72rem; font-weight: 600; text-align: left;
    padding-bottom: 0.1rem; white-space: nowrap;
  }
  .cal-month th {
    font-size: 0.6rem; font-weight: 400; color: var(--fg-soft);
    padding: 0 0.12rem; text-align: center;
  }
  .cal-month td {
    font-size: 0.62rem; text-align: center; padding: 0.05rem 0.12rem;
    font-variant-numeric: tabular-nums; line-height: 1.35;
    border: 1px solid transparent;
  }
  /* 両方 = 塗りつぶし (継続)。色は補強 — 形の区別は素の数字 vs 取消/下線 */
  td.both, .chip.both { background: #1a4f8b; color: #fff; border-radius: 2px; }
  /* 旧のみ = 取り消し線 (この日はなくなった)。④の廃止と同じ語彙 */
  td.old, .chip.old { background: #e2e2e2; color: #444; border-radius: 2px; }
  /* 新のみ = 下線 (新たな運行日)。④の新設と同じ語彙 */
  td.new, .chip.new { background: #0b6e4f; color: #fff; border-radius: 2px; }
  .cal-legend { margin: 0.15rem 0 0.2rem; font-size: 0.72rem; color: var(--fg-soft); }
  .chip { display: inline-block; padding: 0 0.3em; font-size: 0.62rem; }
</style>
