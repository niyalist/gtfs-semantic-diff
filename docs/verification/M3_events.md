# M3 検証ログ: L2 イベントルール第1陣

実施日: 2026-07-04 / コマンド: `gtfs-semantic-diff compare ...` / 出力: `data/m3_*_events.json`

## DoD 判定

| フィード | RawDiff 総数 | explained_ratio | イベント数 | DoD (≥0.95) |
|---|--:|--:|--:|:--|
| 永井運輸 (prev_2 → prev_1) | 14,399 | **1.0000** | 95 | ✓ |
| 富山地鉄バス (prev_1 → current) | 345 | **1.0000** | 13 | ✓ |
| 臨港バステスト (ダイヤ01 → 系統路線増減) | 5,051 | **1.0000** | 4 | ✓ |

各ルールの合成 GTFS 単体テスト: tests/test_rules.py (20件)。pytest 全85件通過。

## 永井運輸: 公式ダイヤ改正メモとの突き合わせ (実フィード目視確認)

フィードの update memo (2025-10-01 改正) に記載された全4項目がイベントとして検出された:

| 公式メモ | 検出イベント |
|---|---|
| マイバス全線で運賃変更 (100円→180円) | `FARE_CHANGED` (fare_rules 6,339 diff を消費) |
| マイバス東循環線がココルンシティに乗り入れ | `STOP_ADDED` (ココルンシティ) + `STOP_INSERTED_IN_PATTERN` (70A/70B 東循環線, 計48便) |
| 西循環線「中央小学校前」→「表町一丁目」改称 | `STOP_RENAMED` (evidence: stop_name field_changed ×2乗り場) |
| 東大室線・前橋玉村線の午後時刻を一部修正 | `TIMETABLE_SHIFTED` (30F 前橋玉村線 9-16時帯ほか) |

その他の主要検出: `ROUTE_DISCONTINUED`「臨時」(31便のカスケード 395 diff を消費)、
`DAYTYPE_RESTRUCTURED` (土曜・休日ダイヤの calendar_dates 化)、`SERVICE_INCREASED` ×43。

## 富山地鉄バス

変化が小さい世代ペア。`PLATFORM_CHANGED` (系統501 の乗り場 2105_01→2105_02 付け替え、
stop_times 22行)、`SHAPE_CHANGED` ×6、`FARE_CHANGED`、`HOLIDAY_EXCEPTION_CHANGED` ×2 で全件説明。

## 臨港バステストデータ

`ROUTE_DISCONTINUED` 鶴１２ + `ROUTE_ADDED` 鶴１２０ (テストデータの意図通り)。
trip カスケード消費により 5,051 diff 中の trips/stop_times 差分を2イベントで説明。

## 説明台帳の設計メモ (M3 で確立した規約)

- 上位イベントは配下の差分をカスケード消費する (ROUTE_DISCONTINUED は
  routes + trips + stop_times の行差分を丸ごと evidence に持つ)。
- 経路変更 (B群) はその trip の stop_times 差分**全体** (時刻連鎖変更・headsign 含む)
  を説明する。経路が変われば下流時刻も変わるため。
- trip 内容署名 (family, 方向, day_type, 停車列, 全時刻) による照合で
  TECHNICAL_ID_CHURN と便数増減を区別する。trip_id の連続性は仮定しない。
- emit と evidence 記録は不可分 (RuleContext.emit) — 付け忘れを構造的に防止。

## M3 スコープ外として残した項目 (roadmap M5)

- ROUTE_SPLIT / ROUTE_MERGED / THROUGH_SERVICE_* (A群の残り)
- TIME_BAND_VARIANT、SHAPE_CHANGED の Fréchet 局在化 (B群詳細)
- TRAVEL_TIME_CHANGED の区間別 quantification (C群詳細)
- FARE_CHANGED の運賃表分解、DEMAND_RESPONSIVE_CHANGE (F群詳細)
- HOLIDAY_EXCEPTION_CHANGED の有効期間正規化 (E群、現状 confidence 0.8 の粗い計上)
