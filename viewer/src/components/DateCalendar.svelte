<script>
  // 特定日運行日のコンパクトカレンダー (2026-07-29 ユーザー仕様)。
  // 月ごとに日曜始まり 7列×5-6行、横に最大6ヶ月で折返し。対象の全日付を含む
  // (「ほかN区間」の省略はしない)。1つのカレンダーに旧/新の両方を塗り、
  // ④時刻表の差分表示と同じ記号語彙 (取り消し=なくなる/下線=新設) を
  // 第1チャネルに、色は補強 (色弱原則)。
  //
  // 期間 (2026-07-29 追補): genWindows (新旧世代の有効期間) があれば、
  // **旧世代の開始月から新世代の終了月まで**を必ず描く (重なりが無くても・
  // 期間が空いても全体)。旧の日付は、新世代データの範囲内なら
  // 「上書きされて消えた日 (取り消し線)」、範囲外なら「旧世代のみが記録する
  // 日 (枠線のみ — 上書きではない)」に区別する — データ全体を通じた
  // 特定日の意味が1枚で読めるようにする。
  import { lang, t } from "../lib/i18n.js";

  export let oldRuns = [];
  export let newRuns = [];
  export let genWindows = null; // {old: [YYYYMMDD, YYYYMMDD], new: [...]} | null

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
  // 描画範囲: 世代の有効期間があればその合併 (旧の開始〜新の終了)、
  // なければ運行日の範囲 (旧版バンドル互換)
  $: span = (() => {
    const o = genWindows?.old;
    const n = genWindows?.new;
    const starts = [o?.[0], n?.[0]].filter(Boolean).sort();
    const ends = [o?.[1], n?.[1]].filter(Boolean).sort();
    if (starts.length && ends.length) return [starts[0], ends[ends.length - 1]];
    const all = [...oldSet, ...newSet].sort();
    return all.length ? [all[0], all[all.length - 1]] : null;
  })();
  $: months = (() => {
    if (!span) return [];
    let y = +span[0].slice(0, 4);
    let m = +span[0].slice(4, 6);
    const endY = +span[1].slice(0, 4);
    const endM = +span[1].slice(4, 6);
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
    if (o && n) return "both";
    if (n) return "new";
    if (o) {
      // 新世代データの範囲内の旧日付 = 新データで上書きされて消えた日。
      // 範囲外なら旧世代だけが記録する日 (上書きではない)。
      // 窓情報がない旧版バンドルでは区別できないので従来どおり「消えた日」
      const nw = genWindows?.new;
      if (!nw?.[0] || !nw?.[1]) return "old";
      return k >= nw[0] && k <= nw[1] ? "old" : "oldout";
    }
    return "";
  }
  function monthLabel(y, m) {
    return $lang === "en" ? `${MONTHS_EN[m - 1]} ${y}` : `${y}年${m}月`;
  }
  const clsOf = (k) => cls(+k.slice(0, 4), +k.slice(4, 6), +k.slice(6, 8));
  $: hasOldOut = [...oldSet].some((k) => clsOf(k) === "oldout") && genWindows;
  $: hasOldIn = [...oldSet].some((k) => clsOf(k) === "old");
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
                  <!-- 塗り・枠は td でなく内側の固定幅ボックス (.d) に付ける。
                       border-collapse の表で td に枠を引くと隣接セルとの辺の
                       解決で欠けて逆L字になる (2026-07-29 実地レビュー) -->
                  <td class={c}>
                    <span class="d">
                      {#if c === "old"}<s>{d}</s>
                      {:else if c === "new"}<u>{d}</u>
                      {:else}{d}{/if}
                    </span>
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
    {#if hasOldIn}／ <span class="chip old"><s>15</s></span> {tt("cal_old_only")}{/if}
    ／ <span class="chip new"><u>15</u></span> {tt("cal_new_only")}
  {:else if oldSet.size}
    {#if hasOldIn}<span class="chip old"><s>15</s></span> {tt("cal_old_side")}{/if}
  {:else}
    <span class="chip new"><u>15</u></span> {tt("cal_new_side")}
  {/if}
  {#if hasOldOut}／ <span class="chip oldout">15</span> {tt("cal_old_outside")}{/if}
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
    font-size: 0.62rem; text-align: center; padding: 0.05rem 0.04rem;
    font-variant-numeric: tabular-nums; line-height: 1.35;
  }
  /* 日付ボックス: 固定幅・角丸。塗り/枠はここに付くので必ず四辺が閉じる */
  .cal-month .d, .chip {
    display: inline-block; min-width: 1.55em; padding: 0 0.08em;
    border: 1px solid transparent; border-radius: 2px;
    box-sizing: border-box; text-align: center;
  }
  /* 両方 = 塗りつぶし (継続)。色は補強 — 形の区別は素の数字 vs 取消/下線 */
  td.both .d, .chip.both { background: #1a4f8b; color: #fff; }
  /* 旧のみ = 取り消し線 (上書きで消えた日)。④の廃止と同じ語彙 */
  td.old .d, .chip.old { background: #e2e2e2; color: #444; }
  /* 新のみ = 下線 (新たな運行日)。④の新設と同じ語彙 */
  td.new .d, .chip.new { background: #0b6e4f; color: #fff; }
  /* 旧世代のみが記録する日 (新世代データの範囲外) = 枠線のみ。
     取り消し線を付けない = 「上書きで消えた」ではないことの記号区別 */
  td.oldout .d, .chip.oldout { border-color: #8a929e; color: #444; }
  .cal-legend { margin: 0.15rem 0 0.2rem; font-size: 0.72rem; color: var(--fg-soft); }
  .chip { display: inline-block; padding: 0 0.3em; font-size: 0.62rem; }
</style>
