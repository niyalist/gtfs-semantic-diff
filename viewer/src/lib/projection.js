// 表示射影 (ui_quality.md S4): bundle.presentation から「ユーザーが読む文字列」
// だけを抽出する。要点は、コンポーネントと同じ整形実装 (format.js / i18n.js) を
// 通ること — サーバー側の変更が表示文字列をどう変えるかを、ブラウザなしの
// スナップショットで固定できる。scripts からも実 bundle に対して使える。
import { countText, runsText } from "./format.js";
import { dayName, translator } from "./i18n.js";

export function projectPresentation(pres, language = "ja") {
  const tt = translator(language);
  const lines = [];
  // 第1部: 曜日区分ごとの便数 (PI-1: 第3部の合計と一致するはず)
  for (const d of pres.feed_overview?.day_types ?? []) {
    lines.push(`P1 ${dayName(d.day_type, language)} ${countText(tt, d)}`);
  }
  for (const p of pres.route_pages ?? []) {
    // 折りたたみヘッダ (R19) と曜日タブは同じ countText を通る
    const head = (p.day_totals ?? [])
      .map((d) => `${dayName(d.day_type, language)} ${countText(tt, d)}`)
      .join(" ");
    lines.push(`P3 ${p.route_group} | ${head}`);
    // SD5b セルの日付注記 (cellDates と同じ runsText)
    for (const [day, m] of Object.entries(p.day_cells ?? {})) {
      const parts = [];
      if (m.dates_old_total)
        parts.push(`${tt("old_gen")}: ${runsText(m.runs_old, m.runs_old_more, m.dates_old_total, language)}`);
      if (m.dates_new_total)
        parts.push(`${tt("new_gen")}: ${runsText(m.runs_new, m.runs_new_more, m.dates_new_total, language)}`);
      lines.push(
        `P3 ${p.route_group} [${dayName(day, language)}] ${parts.join(" → ")} (${m.signal})`
      );
    }
  }
  for (const c of pres.self_check ?? []) {
    lines.push(`SELF-CHECK ${c.route_group} ${c.day_type} header=${c.header} timetable=${c.timetable}`);
  }
  return lines;
}
