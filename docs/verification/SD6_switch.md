# SD6 検証ログ: 切替の整列 (2026-07-25)

設計: service_days.md §9.2。実装: events/day_worlds.py
resolve_generation_switch + pipeline._resolve_switch_scope (SD2 の前段。
不発時は SD2 に委譲)。除外分の claim は既存 GENERATION_SCOPE 機構を流用、
switch_date を scope context と「比較の概要」(条件段) に表示。

## 判定規則 (実装)

レギュラー型ラベルのうち複数世界を持つ全ラベルで:
- 旧が複数世界 → 末尾世界の内容が新に存在 (持ち越し) かつ先頭世界の内容は
  新に不在 (再出現なし = 季節でない)
- 新が複数世界 → 先頭世界の内容が旧に存在 (先行同梱) かつ末尾世界は旧に不在
成立時「旧の初期世界 vs 新の最終世界」で比較。特定日/inactive は従来どおり。

## DoD 実測 (桑名3世代 ほか)

| ペア | 結果 |
|---|---|
| A+B vs B (0710二重→0723) | **switch=7/11、TIMETABLE_SHIFTED 32 / REDUCED 10 / churn 53** — 基準 A vs B (29/9/53) と主要一致。旧「変化なし (20 events)」の誤りが解消。explained 1.0 |
| A vs A+B (0703→0710) | switch=7/11 明示 (従来は SD2 (b) が同等の除外。イベント同水準)。explained 1.0 |
| A vs B (0703→0723) | 単世界 → 不発。イベント JSON バイト一致 (退化保証) |
| しんぐう (季節) | 不発 (再出現ガード)。SERVICE_* 0 のまま |
| 佐賀 (寄せ集め) | 不発 → SD2 経路のまま (三瀬神埼線ガード維持)。explained 0.9997 |
| trimet (四半期) | 不発 (四半期は内容不一致で持ち越し条件を満たさない) |
| 合成テスト | test_generations.py を SD6 契約に更新 (旧側除外が WD_A→WD_B に反転、switch_date 検証)。pytest 235 |

## 記録: trimet の events 4535→4598 について

SD5 コア導入時の「trimet バイト一致」は計測スクリプトが day_worlds 未接続の
旧段組みだったための見かけ。実パイプラインでは trimet の multi-world 群に
SERVICE_DAYS_CHANGED 等が出る (意図された変化)。1世界系 (桑名 A vs B) の
バイト一致は実パイプラインでも成立。
