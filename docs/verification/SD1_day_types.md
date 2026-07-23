# SD1 検証ログ: day_type 分類の実効運行日ベース化 (2026-07-23)

設計: docs/design/service_days.md §2.1。仕様: detection.md §0 (SD1 節)。
実装: load/day_types.py (`_effective_day_stats` + 密度判定)、loader.py
(`_feed_window`)。閾値: `[load.day_types] min_flag_day_ratio = 0.5` (新設)。

## ルール (実装済み)

曜日フラグを持つ service に対し、実効運行日 = (期間×フラグ − calendar_dates
削除 + 追加、フィード有効期間でクリップ) を数え:

- 実効日ゼロ → `inactive` (期限切れ残骸 T6)
- 密度 (実効日/フラグ該当日) < 0.5 → `irregular` (祝日専用 service T1)
- それ以外 → 従来のフラグ分類 (変更なし)

設計過程の記録: 当初「実効日数 ≤ short_service_max_days (10) → irregular」の
**日数閾値**で実装したが、実データ検証で STM (四半期 period 分割) の正規
土曜ダイヤ (11土曜−祝日1 = 10日) が 81/114 service 誤爆することが判明し、
**密度閾値**に置き換えた。祝日専用 (PRT 密度 0.06) と期間分割正規ダイヤ
(STM/桑名 0.9〜1.0) は密度で明確に分離できる。

## 合成テスト (tests/test_day_types.py、全210件通過)

- T1: 土曜フラグ+通常土曜全削除+祝日1日 → irregular (通常土曜 service は不変)
- T6: 期間がフィード窓の丸ごと外 → inactive / 全日削除 → inactive
- 密度: 短期間 (土曜6回・削除なし = 密度1.0) は saturday を維持 (STM/同居型)
- 回帰: 期間カラムなし・通常 service・dow_* は従来どおり

## 実フィード検証

### 分類差分の総点検 (旧分類 = フラグのみ、との比較)

| フィード | 分類変化 |
|---|---|
| 名古屋 (2世代)・臨港 (2世代)・佐賀 (4世代)・三重 中勢/桑名5スナップショット | **全て不変** (同居 kuwana_prev19 含む — T2 の扱いは SD2 に純粋分離) |
| trimet / stm / rome (各2世代) | **不変** (STM 誤爆は密度化で解消) |
| prt old | メモリアルデー専用 dow_1000000 → irregular (1件) |
| prt new | 独立記念日 saturday → irregular、レイバーデー dow_1000000 → irregular、期限切れ W/U/S → inactive (計5件) |
| mbta old / new | 期限切れ rating の service → inactive (95 / 269件)。T6 の正しい検出 — 過去/将来 rating の便が便数に混入していた |

### イベント JSON の A/B 一致 (git stash による新旧コード比較)

名古屋・臨港・佐賀の3ペアで、SD1 前後のイベント JSON が
**config_snapshot (新閾値の記録) を除き完全一致**。

### PRT (IN-8 の解消確認)

| 指標 | SD1 前 | SD1 後 |
|---|---|---|
| route 1 土曜 | 38→**76** (見かけ倍増) | 38→**38** ✓ |
| route 21 土曜 | 38→76 | 38→38 ✓ |
| 偽「月曜 38便」列 | あり | 消滅 (特定日へ) ✓ |
| irregular 列 | — | 38→76 (旧=メモリアルデー1日 / 新=独立記念日+レイバーデー2日。事実どおり) |
| explained_ratio | 0.9999 | **1.0000** |
| イベント数 | 4,184 | 4,221 |

## 既知の影響・留意

- mbta は期限切れ service の便が便数集計から外れるため day_totals が変わる
  (改善方向)。I1 台帳の実行記録は P1 時点の数値のまま (注記済み)。
- trimet の祝日 service は「祝日1日だけの短い期間 (密度1.0)」という別方式の
  ため分類は変わらない (現行挙動維持 = 保守的)。特定日への寄せは
  日数閾値の議論であり、桑名同居の残存窓とのトレードオフから見送り
  (service_days.md 監査 §0 の方針どおり)。
- feed_info も世代メタも無いフィードは窓クリップなし (実効日は calendar
  期間のまま) — T6 検出はフィード側の期間情報がある場合に限る。
