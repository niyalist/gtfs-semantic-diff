# gtfs-semdiff — GTFS 意味的差分抽出ツール

複数世代の GTFS フィードを比較し、変化を「人間が認識できる意味」(路線廃止、減便、区間短縮、乗り場変更など)として抽出・レポートする CLI ツール。GTFSデータリポジトリ (https://gtfs-data.jp) の世代管理 API と連携する。

## 最重要設計原則

1. **説明会計 (explanation accounting)**: L0 で検出した生差分(全ファイル・全フィールド)は、必ずいずれかの ChangeEvent の `evidence` に紐づくか、`UNEXPLAINED_RESIDUAL` としてレポートされる。**網羅性はこの会計で構造的に保証する。** 被覆率(explained ratio)は常に計測・表示する。
2. **データモデルは1つ**: 新旧2つのモデル体系を並走させない。モデル変更が必要なら移行を完遂してから次へ進む(前プロジェクト最大の失敗要因)。
3. **JSON イベントストリームが安定インタフェース**: コアは「GTFS スナップショット2つ → ChangeEvent JSON」の純粋関数。CLI / 将来の Web / GUI はすべてこの JSON の消費者。レポート生成器はコアに依存するがコアはレポートを知らない。
4. **検出は決定的ルールベース**: 機械学習・LLM をコアの検出/分類に使わない。閾値はすべて設定ファイルで明示。LLM の使用はレポートの自然言語化(任意機能、事実・数値は JSON から)に限定。
5. **早すぎる最適化の禁止**: まず正しく、次に速く。最適化は実データでの計測結果を docs/perf/ に記録してから行う。デバッグ用の路線名ハードコード禁止(前プロジェクトの反省)。

## アーキテクチャ

```
input (zip x N generations | gtfs-data.jp API)
  → load/      GTFS 読み込み・正規化 (GtfsSnapshot)
  → diff0/     L0: 網羅的機械diff (RawDiff の全列挙)
  → identity/  L1: 世代間同定 — stop cluster / route family /
               パターンクラスタ / 運行日種別 の対応付け
  → events/    L2: ルールカスケードで ChangeEvent 抽出、
               evidence として RawDiff を消費、残差計算
  → 出力: ChangeEvent JSON (正) + report/ で Markdown レポート
```

詳細は docs/design/architecture.md、イベント定義は docs/design/ontology.md を必ず読むこと。

## 過去プロジェクトからの資産移植

前身: `/Users/niya/Documents/itolab/2025/gtfsdiff/GTFSDiff` (読み取り参照のみ。共存させず、必要部分を本リポジトリの新モデルに合わせて移植する)。対応表は docs/PORTING.md。特に価値が高いもの:

- `src/gtfs_diff/analysis/pattern_clustering.py` — 停車パターンの LCS 類似度クラスタリング (O(patterns²) 最適化済み)
- `src/gtfs_diff/analysis/route_analyzer.py` — Route Family 概念 (route_id でなく路線名でグループ化)
- `src/gtfs_diff/analysis/stop_analyzer.py` — 2段階 Stop Clustering (世代内名寄せ+近接 → 世代間リンク)
- `src/gtfs_diff/repository.py` — gtfs-data.jp API v2 クライアント

## gtfs-data.jp API メモ (2026-07 動作確認済み)

- Base: `https://api.gtfs-data.jp/v2`
- `GET /feeds?pref=<id>` / `GET /feeds?org_id=<id>` — フィード一覧
- `GET /organizations/{org_id}/feeds/{feed_id}?max_prev=N` — 世代付きファイル一覧
- RID 体系: `current`, `prev_1`, `prev_2`, …

## 検証フィード (回帰テストの基準)

1. 永井運輸 `nagai-unyu / Nagaibus` (API 取得可・小規模)
2. 富山地方鉄道 (API)
3. 川崎鶴見臨港バス (ローカル zip、大規模・性能検証用)

## 開発ルール

- マイルストーンと Definition of Done は docs/design/roadmap.md に従う。**DoD を満たすまで次のマイルストーンに着手しない。**
- 「完了」と記録してよいのは、検証フィードでの実行結果を確認したときのみ。
- 各 ChangeEvent ルールには必ず: 検出条件のドキュメント、合成 GTFS による単体テスト、実フィードでの目視確認例、の3点を付ける。
- 閾値(距離、類似度、時間帯ビン等)は `config/default.toml` に集約。コード内リテラル禁止。
- 日本語出力が第一級。イベントタイプは英語 ID + 日本語表示名を対で管理。
