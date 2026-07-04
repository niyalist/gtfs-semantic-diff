# ChangeEvent オントロジー v0.2

## イベントの構造

```json
{
  "event_id": "evt_000123",
  "type": "SERVICE_REDUCED",
  "subject": {
    "route_family": "41号線",
    "direction": "outbound",
    "pattern_cluster": "cluster_003",
    "day_type": "weekday"
  },
  "old_ref": {...}, "new_ref": {...},
  "quantification": {"time_band": "9-16", "old_count": 21, "new_count": 14},
  "evidence": ["rawdiff_00871", "rawdiff_00872", "..."],
  "confidence": 0.94,
  "severity": "major",
  "display_name_ja": "日中時間帯の減便",
  "narrative_hints": {...}
}
```

- `evidence`: このイベントが「説明」する L0 RawDiff の ID リスト。**説明会計の台帳。** 1つの RawDiff を複数イベントが参照してよい(多対多)が、主説明イベント(primary)を1つ持つ。
- `confidence`: L1 同定の確信度を伝播した値。同定が仮説的(例: 時刻接続推定)なら低くなる。
- `severity`: 利用者影響度 `major | minor | info`。confidence とは独立の軸。
- 量的イベントは閾値で切り捨てず数値を保持し、表示側で解釈する。

## カタログ

### A. 路線・系統レベル (subject: route family)

| type | 検出ルール概要 | severity |
|---|---|---|
| `ROUTE_ADDED` / `ROUTE_DISCONTINUED` | family の出現・消滅。ただし RENAMED / SPLIT / MERGED の照合(パターン類似度)を先に行い、残ったものだけ確定 | major |
| `ROUTE_RENAMED` | パターン集合がほぼ同一 (Jaccard ≥ 閾値) で名称のみ変化 | minor |
| `ROUTE_SPLIT` / `ROUTE_MERGED` | 1 family のパターン集合が複数 family に分配される / 逆 | major |
| `THROUGH_SERVICE_INTRODUCED` / `_DISCONTINUED` | **新パターンが旧世代の異なる family の2パターンの連接 (concatenation) として説明できる**(接合点停留所が一致、時刻が連続)。想定は「1本の trip に統合」ケース | major |

### B. 運行パターンレベル (subject: family × 方向 × パターンクラスタ)

| type | 検出ルール概要 | severity |
|---|---|---|
| `PATTERN_EXTENDED` / `PATTERN_TRUNCATED` | 新パターンが旧パターンの上位列 / 接頭・接尾部分列 | major |
| `STOP_INSERTED_IN_PATTERN` / `STOP_REMOVED_FROM_PATTERN` | 編集距離での挿入・削除(1〜n 停留所)。「途中にバス停が追加された」 | minor |
| `DETOUR_ADDED` / `DETOUR_REMOVED` | 連続部分列の挿入・削除(施設経由等)。挿入列の前後が一致 | minor–major |
| `TIME_BAND_VARIANT` | あるパターンクラスタの出現が特定時間帯・曜日種別に限定される/されなくなった。「特定の時間帯だけ施設を経由」 | minor |
| `SHAPE_CHANGED` | **停車パターンは同一だが shapes.txt の経路形状が変化**。離散 Fréchet 距離(または簡易には点列 Hausdorff)が閾値超。停留所間の区間単位で局在化して報告 | minor |

### C. 便数・時刻レベル (subject: family × 方向 × パターン × 運行日種別; 比較対象は出発時刻の集合)

trip_id の連続性は一切仮定しない。時間帯ビン既定値: 5–7 / 7–9 / 9–16 / 16–19 / 19–22 / 22–翌5 (config で変更可)。

| type | 検出ルール概要 | severity |
|---|---|---|
| `SERVICE_REDUCED` / `SERVICE_INCREASED` | ビンごとの本数増減 | major(通勤帯)/minor |
| `TRIPS_TRUNCATED` | 本数が full パターンから truncated パターンへ移動(family 合計はほぼ保存)。「終点まで行く便の一部打ち切り」 | major |
| `FIRST_LAST_CHANGED` | 始発繰り下げ・終発繰り上げ等 | major |
| `TIMETABLE_SHIFTED` | 時刻集合のほぼ一様なシフト(中央値シフト・分散小) | info |
| `TRAVEL_TIME_CHANGED` | **区間別(停留所ペア別)・曜日種別・時間帯別の所要時間変化。** 標準所要時間の分布変化として検出し、ダイヤ余裕(スラック)の増減を追える粒度で quantification に保持: `{segment, day_type, time_band, old_median_sec, new_median_sec, old_p90, new_p90}` | minor |
| `DWELL_TIME_CHANGED` | 同一停留所での arrival/departure 差(停車時分)の変化。余裕時分分析の補助 | info |

### D. 停留所レベル (subject: stop cluster / platform)

| type | 検出ルール概要 | severity |
|---|---|---|
| `STOP_ADDED` / `STOP_REMOVED` | クラスタ単位の新設・廃止 | major |
| `STOP_RENAMED` | 位置・路線接続が同一で名称変化 | minor |
| `STOP_RELOCATED` | 同一名・同一接続で座標が閾値(既定 300m)超移動 | minor |
| `PLATFORM_CHANGED` | stop_id 変化だが同一クラスタ内(prefix 一致・近接)。「乗り場変更」 | minor |
| `PLATFORM_ADDED` / `PLATFORM_REMOVED` | クラスタ内プラットフォーム数の増減 | info |

### E. 運行日・カレンダー (subject: service pattern)

| type | 検出ルール概要 | severity |
|---|---|---|
| `DAYTYPE_RESTRUCTURED` | 曜日区分の再編(例: 土曜ダイヤ廃止→休日へ統合)。calendar の正規化後に day_type 集合を比較 | major |
| `HOLIDAY_EXCEPTION_CHANGED` | calendar_dates の例外差分(有効期間の重なりで正規化して比較) | info |
| `SEASONAL_SERVICE_CHANGED` | 期間限定サービスの出現・消滅 | minor |

### F. 運用形態・メタデータ・形式層 (網羅性の受け皿)

| type | 検出ルール概要 | severity |
|---|---|---|
| `DEMAND_RESPONSIVE_CHANGE` | **GTFS で追える範囲でのデマンド化・予約制移行の兆候**: stop_times の `pickup_type`/`drop_off_type` が 2(要電話)/3(要調整)へ変化、`continuous_pickup/drop_off` の変化、GTFS-Flex 系ファイル(booking_rules, location_groups)の出現、frequencies.txt への移行。単独では断定できないため confidence を明示し、複数兆候の合成で昇格 | major |
| `FARE_CHANGED` | fare_attributes / fare_rules の差分(運賃改定) | major |
| `FEED_VALIDITY_CHANGED` | feed_info の期限・calendar 末尾の書き換え | info |
| `AGENCY_INFO_CHANGED` / `TRANSLATION_CHANGED` | agency / translations の差分 | info |
| `ACCESSIBILITY_CHANGED` | wheelchair_boarding / wheelchair_accessible の変化 | minor |
| `TECHNICAL_ID_CHURN` | **意味的変化を伴わない ID 張り替え**(例: trip_id 全交換だがダイヤ同一)。L1 同定で同一と判定された対の ID 差分をまとめて説明する。データ更新の健全性検証に使う | info |
| `UNEXPLAINED_RESIDUAL` | どのルールでも説明されなかった RawDiff。**ここの件数と内訳がルールカタログ育成の KPI** | — |

## 抽出カスケード (順序が重要)

依存グラフ: stop 同定 → route family 同定 (RENAMED/SPLIT/MERGED を ADDED/DISCONTINUED より先に確定) → パターン照合 (EXTENDED/TRUNCATED/挿入/連接) → 時刻集合比較 → カレンダー → メタデータ → ID churn → 残差。

貪欲な早期確定を避け、各段の対応付けは confidence 付き仮説として保持し、下流の整合性で裏づけがあれば昇格する。

## 被覆率の定義

`explained_ratio = 1 - |UNEXPLAINED_RESIDUAL evidence| / |RawDiff 全体|`
をフィード比較ごとに算出しレポート末尾に必ず表示。目標: 検証3フィードで 0.99 以上。
