# M5 検証ログ: 残差追い込みと E/F 群詳細化

実施日: 2026-07-04 / 出力: `data/m5_*_events.json`

## DoD 判定

| フィード | RawDiff | explained_ratio | 実時間 | DoD (≥0.99, 5分以内) |
|---|--:|--:|--:|:--|
| 永井運輸 (prev_2→prev_1) | 14,399 | **1.0000** | 1.17 s | ✓ |
| 富山地鉄バス (prev_2→prev_1, R8改正) | 30,700 | **1.0000** (M4 時点 0.9960) | 1.89 s | ✓ |
| 臨港バステスト (ダイヤ01→系統路線増減) | 5,051 | **1.0000** | 1.15 s | ✓ |

性能詳細は docs/perf/M5_timings.md。pytest 99 件通過 (M5 新規 11 件)。

## 残差追い込みの内訳 (地鉄 R8 の残り 124 件 → 0 件)

1. **headsign 変更 120 件** (「14富山駅前（…）」→「14富山駅（…）」):
   カタログに該当タイプが無かったため `HEADSIGN_CHANGED` (行先表示変更, info)
   を ontology v0.2.1 として採録。UNEXPLAINED_RESIDUAL がルールカタログを
   育てるという設計ループの初適用例。
2. **停留所「神明」の 385m 移設 4 件**: 世代間リンクの空間絞り込み
   (inter_generation_radius 300m) を超える移設で同定漏れ → stop_id を共有する
   クラスタは距離に関係なくリンク候補に含めるよう identity を修正。
   `STOP_RELOCATED` (moved_m=385.3) として検出されることを実データで確認。

## E/F 群の詳細化 (実データでの目視確認)

- **SHAPE_CHANGED**: 離散 Fréchet 距離で実変形 (significant=true, 44件,
  例: 堤防・熊野経由八尾・萩の島循環線 588m) と点列振り直し等 (51件, info)
  を判別。shape_id 張り替えは幾何一致なら TECHNICAL_ID_CHURN (合成テストで確認)。
- **TRAVEL_TIME_CHANGED**: 区間別 {segment, old/new_median_sec, old/new_p90}
  を quantification に保持 (ダイヤ余裕分析の粒度)。
- **HOLIDAY_EXCEPTION_CHANGED**: 新旧有効期間の重なり窓で正規化。地鉄 R8 では
  within_overlap 10 / outside_overlap 4 (期間スライドの機械差) に分離、
  confidence 0.8 → 1.0 に昇格。
- **FARE_CHANGED**: 運賃表分解 (removed/added_fares, price_changes)。
  合成テストで 100円廃止+180円新設+500→520円改定の分解を確認。
- **DEMAND_RESPONSIVE_CHANGE**: pickup/drop_off_type 2・3 への変化、
  continuous_*、booking_rules/location_groups/frequencies 出現の兆候合成
  (1兆候 conf 0.5 〜 複数 0.9)。
- **SEASONAL_SERVICE_CHANGED**: 全 trip が特定日運行 (irregular) の family の
  出現・消滅を季節サービスとして報告 (conf 0.6)。

## 既知の限界

- 地鉄のぶりかにバスは通常の平日/土日祝 service で記述されており (calendar 上は
  毎日運行相当)、**GTFS データ単体には季節性の手がかりがない**。このため
  ROUTE_DISCONTINUED のまま (データに忠実)。季節性の同定は多世代タイムライン
  分析 (将来の events/timeline.py) の課題。
- SHAPE_CHANGED の停留所間区間への局在化は未実装 (最大乖離点の座標で代替)。
