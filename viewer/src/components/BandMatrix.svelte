<script>
  import { lang, t, dayName } from "../lib/i18n.js";

  export let matrix; // {bands, rows}
  $: tt = $t;
  $: bands = matrix.bands.filter((b) =>
    matrix.rows.some((r) => r.cells[b])
  );

  function dayJa(d) {
    return dayName(d, $lang);
  }
  function cellText(v) {
    if (!v) return "";
    const [o, n] = v;
    if (o === n) return String(n);
    return `${o}→${n}${n > o ? "▲" : "▼"}`; // 数値+記号が第1チャネル (原則5)
  }
  function cellClass(v) {
    if (!v || v[0] === v[1]) return "";
    return v[1] > v[0] ? "inc" : "dec";
  }
</script>

<div class="scroll-x">
  <table>
    <thead>
      <tr>
        <th>{tt("direction")} / {tt("route")}</th>
        <th>{tt("day")}</th>
        {#each bands as b}<th class="num">{b}</th>{/each}
        <th class="num">{tt("total")}</th>
      </tr>
    </thead>
    <tbody>
      {#each matrix.rows as r}
        <tr class:agg={r.kind === "aggregate"} class:leg={r.kind === "leg"}>
          <td class={r.kind === "system" ? "indent2" : r.kind === "leg" ? "indent" : ""}>
            {r.kind === "system" ? "└ " : r.kind === "leg" ? "└ " : ""}{r.label}
          </td>
          <td>{dayJa(r.day_type)}</td>
          {#each bands as b}
            <td class="num {cellClass(r.cells[b])}">{cellText(r.cells[b])}</td>
          {/each}
          <td class="num {r.total[0] !== r.total[1] ? (r.total[1] > r.total[0] ? 'inc' : 'dec') : ''}">
            <strong>{cellText(r.total)}</strong>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  tr.agg td { font-weight: 600; background: var(--bg-soft); }
  tr.leg td { font-weight: 600; } /* ④時刻表の表題と同ラベル・同便数の方向行 */
  td.indent { padding-left: 1.4em; }
  td.indent2 { padding-left: 2.9em; }
  td.inc { background: #fff3e6; } /* 補強のみ: 記号▲▼が第1チャネル */
  td.dec { background: #e8f0f7; }
</style>
