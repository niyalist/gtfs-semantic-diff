# ルール段 (L2) の非線形2件の特定と修正 — P2/IN-1 (2026-07-24)

## 背景

I1 実測 (docs/verification/intl_feeds.md IN-1) で、ルール段が RawDiff 大量時に
非線形化する疑い (MBTA 616s / rome 996s / trimet 47s / prt 99s)。cProfile +
ルール毎の実時間計測 (trimet) で 2 つの O(n²) を特定した。

## 特定した非線形 (2件)

### 1. frequency ルール: グループ毎の全 trip 再走査 — O(グループ数 × trip 数)

`events/rules/frequency.py _band_events / _first_last_event` が、
(family × 方向 × day_type) グループ毎に `trip_delta.old_trips / new_trips`
**全件**を再走査していた (グループ総数・ビン別本数・始発終発の3箇所)。
trimet で `_group_key` 呼び出し **1億2700万回**。trip 数 T とグループ数 G の
積で効くため、大規模フィードほど非線形に悪化する。

修正: グループ別総数・(グループ, ビン) 別本数・始発時刻列を **1パスで事前集計**
(Counter / defaultdict)。O(T + G×B) に。

### 2. MatchGraph: 照会毎の全エッジ走査 — O(照会数 × エッジ数)

`model/matchgraph.py matches_for_old / matches_for_new` が呼び出しの度に
`edges` 全件を線形走査していた。stops ルールはクラスタ毎 + stop_times の
stop_id 付け替え差分毎にこれを呼ぶため、クラスタ・差分が多いフィードで爆発
(prt の stops ルール単体で 67s)。

修正: (entity_type, ID) → エッジ列の辞書索引を遅延構築 (`add()` で無効化)。
confidence 降順ソートは索引構築時に1回。安定ソートのため同 confidence の
順序は従来の `sorted(全走査結果)` と完全一致。

## 実測 (I1 データセット、ローカル Mac、caffeinate 付き)

ルール段 (CASCADE 実時間)。「旧」は同一計測ハーネスでの HEAD (2026.7.24.1):

| feed | ルール段 旧 | ルール段 新 | 内訳 (新) |
|---|---|---|---|
| trimet | 23.0s | **14.7s** | frequency 12.1→4.2s |
| prt | 92.1s | **20.8s** (4.4x) | stops 67.2→<0.5s、shapes 16.0s が残存 |
| mbta | 616s (I1 台帳) | **33.6s** (18x) | frequency 11.5s / shapes 8.1s |
| rome | 996s (I1 台帳) | **80.9s** (12x) | shapes 39.0s / technical 14.6s / patterns 12.5s |

全体所要 (参考): prt 134s → 62s、mbta 1010s → 932s、rome 1523s → 640s。
ルール段修正後の支配項はいずれも便対応 (tripdelta): mbta 792s / rome 401s = IN-2。
rome のイベント数 (11,015)・explained (0.9834) は I1 台帳と一致。

## 出力の同一性

- イベント JSON (evidence 含む全フィールド) を修正前後でバイト比較:
  **trimet (4535件)・prt (4221件)・名古屋 20250329→20260328・
  桑名 20260703→20260723 (SD2 scope 発動経路) すべて完全一致**
- pytest 224件・ruff 通過

## 残る支配項 (次の候補)

- **便対応 (tripdelta) = IN-2**: mbta 792s / rome 401s / trimet 190s。
  ルール段修正後の最大支配項。Δt 計算×候補対とタプルハッシュが残コスト
- shapes ルールの離散 Fréchet (純 Python 200×200 DP、1ペア数十 ms):
  rome 39.0s / prt 16.0s。変更 shape 数に線形だが係数が大きい
- `EvidenceLedger.consume`: evidence 総量に線形 (trimet で 8.4s/1000万 ID)。
  非線形ではないが evidence 多重度の高いフィードで効く
