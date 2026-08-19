# IM1 検証: mapping.json (ID 対応表)

2026-07-30。IM1 (docs/design/ai_interface.md §5.1、実装:
src/gtfs_semantic_diff/report/mapping.py) の検証記録。

## 検証項目と結果

### 1. 合成テスト (tests/test_mapping.py、3件)

- relation 語彙の妥当性 (stops/routes/trips)、N:M が常に配列であること
- trips の保存則: exact+modified+removed+added = TripDelta の全件数
- 改称 (市役所前→表町一丁目) が同一クラスタの対応+renamed として現れ、
  両側に GTFS stop_id・関連イベント参照が付くこと
- CLI `--mapping` / `--digest-routes` の出力

### 2. 永井運輸 (prev_2→prev_1、2025-10-01 改正) — 公式発表との一致

stops: **継続213 + 改称1 + 廃止3 + 新設1** (計218クラスタ)。

- 改称: 中央小学校前 → 表町一丁目 (confidence 0.85、evt_000001) — 告知どおり
- 廃止: 旧日赤入口・朝貝橋・朝日町県営住宅前 / 新設: ココルンシティ — 告知どおり
- 偽の対応 (下記の初版不具合) ゼロ

### 3. 朝日町 (prev_1→current、21→9 路線統合) — N:M 保持の錨

routes: **MERGED 7 + RENAMED 2** — M9 検証 (route identity v2) の錨と完全一致。
例: ［市振線］系3 family+［宮崎境線］役場便 → A2市振線 が old 4件の配列の
まま出力される (1:1 に潰していない)。similarity 付き。

## 実装教訓 (初版の不具合と確定した規則)

初版は MatchGraph の stop_cluster エッジを全件直列化していたが、graph は
**対応仮説** (ルール段が棄却した低信頼の近接候補、双方向重複を含む) の
置き場であり、永井で「三河町→境橋 (conf 0.29)」級の偽改称が150件以上
混入した。修正 (2026.7.30.5) で規則を確定:

> **mapping = 説明台帳が採択した対応のみ。**
> stops = 同名クラスタの継続 + STOP_RENAMED イベントの採択対 + 残余の
> added/removed。routes = M9 family_components + 同名継続のみ
> (名前違いの graph エッジは出さない)。

これは説明台帳の思想 (全主張は採択された証拠に遡れる) の ID 版であり、
docs/api/reference.md §8 の契約 (「.4 の mapping は使わない」注意を含む)
に反映済み。

## 残 DoD (IM3)

消費者シミュレーション: 合成乗降データ (旧 stop_id/trip_id キー) を
mapping 経由で新世代に結合し、件数保存を機械検査。実フィード錨に
名古屋 (鳴.ワイ→鳴.メグ の route_id 同一改称) を追加予定。論文の応用節候補。
