# SD5 検証ログ: 運行日世界 (2026-07-25)

設計: service_days.md §9.1 / 検証データ: day_pattern_survey.md。
実装: events/day_worlds.py (世界分解・パターン束ね・2信号対応) +
rules/frequency.py の世界セル化 + SERVICE_DAYS_CHANGED (ontology v0.2.4)。

## DoD 実測

| 項目 | 結果 |
|---|---|
| PRT 特定日 (発端事例) | **SERVICE_DAYS_CHANGED 85件** (「5/25 → 7/4・9/7、N便/日」方向別)。見かけ倍増 38→76 が消滅。explained 1.0000 |
| STM 四半期 | explained 1.0000。SERVICE_* の分母が世界毎 (例 316/0 — ラベル合算 31,791 の過大が消滅)。年度またぎの内容一致は SDC (土曜 150便/日、2025四半期→2026四半期) |
| 退化保証 | 桑名 0703/0723・trimet: イベント JSON **バイト一致** (1世界系は従来計算のまま)。pytest 235 |
| 河内小 (内容一致・年度ずれ) | explained 1.0000、疑似イベントなし (パターン対応が日付ずれを吸収) |
| しんぐう (季節2世界・再出現) | SD5 起因の変化なし (SDC も増減便も出ない — 再出現パターンは exact 照合で吸収)。residual (routes/trips 29件) は SD5 無効時と同一 = 既存の claim 漏れ |
| 新庄 (日付一致・内容変化) | dates 信号で対応、差分は STOP_*/便対応が説明。residual (stops 70件) も既存 |

## 未了 (SD5 残作業)

- 表示層: day_totals・曜日タブ・特定日タブの世界/パターン化 (bundle/viewer)。
  現状はコア (events JSON) のみ世界化済みで、レポート表示は従来集計のまま
- 名古屋ほか国内検証フィードの multi-world 群の目視確認
- しんぐう/新庄の既存 claim 漏れは別課題 (IN-5 系) として台帳へ
