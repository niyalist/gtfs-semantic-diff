# ロードマップと Definition of Done

原則: **DoD を満たすまで次のマイルストーンに着手しない。** 「動いた気がする」は完了ではない。

> 状態 (2026-07-04): **M0〜M5 すべて完了。** 各 DoD の実行結果は docs/verification/ と
> docs/perf/ に記録済み。M0: 673d24e / M1: 036cb0c / M2: 3e04dce / M3: 9168e6f /
> M4: 7150471 / M5: 9733446。以降の作業対象は「将来」節。

## M0: 骨格と読み込み

- model/ のデータクラス定義 (GtfsSnapshot, RawDiff, MatchGraph, ChangeEvent)
- load/: zip 読み込み + calendar→day_type 正規化
- load/repository.py: 旧 `repository.py` を移植し、永井運輸の current / prev_1 を実取得
- DoD: `gtfs-semdiff fetch --org nagai-unyu --feed Nagaibus` で2世代の zip がキャッシュされ、Snapshot として読める。pytest 通過。

## M1: L0 網羅diff + 説明会計の土台

- diff0/: 全ファイル・全フィールドの RawDiff 列挙と安定 ID
- events/accounting.py: evidence 台帳と explained_ratio 算出 (この時点では全件 UNEXPLAINED)
- DoD: 永井運輸2世代で RawDiff 全列挙、JSON 出力、`explained_ratio = 0` が正しく出る。件数がファイル別に集計される。

## M2: L1 同定 (資産移植の中心)

- identity/stop_clustering.py ← 旧 stop_analyzer.py の2段階クラスタリング
- identity/route_family.py ← 旧 route_analyzer.py
- identity/pattern_clustering.py ← 旧 pattern_clustering.py (デバッグ用ハードコードは除去)
- DoD: 3検証フィードで MatchGraph が生成でき、stop/route の対応率と confidence 分布を目視確認したログを docs/verification/ に残す。

## M3: L2 イベントルール第1陣

- D群 (停留所) → A群 (路線) → B群 (パターン) → C群 (便数・時刻) の順に実装
- TECHNICAL_ID_CHURN と accounting の接続
- DoD: 永井運輸・富山地鉄で explained_ratio ≥ 0.95。各ルールに合成 GTFS の単体テスト。

## M4: Markdown レポート

- report/markdown.py: 京都市別紙風・路線ごと章立て + データ検証章
- DoD: 富山地鉄の実改正でレポートを生成し、公式のダイヤ改正告知と突き合わせて主要変更が拾えていることを確認。

## M5: 残差追い込みと E/F 群

- SHAPE_CHANGED, TRAVEL_TIME_CHANGED 詳細, DEMAND_RESPONSIVE_CHANGE, FARE_CHANGED, カレンダー群
- DoD: 3フィードで explained_ratio ≥ 0.99。臨港バス(大規模)で実用時間内(目安: 5分以内)に完走。

## 将来 (スコープ外だが JSON 互換を壊さない)

- 多世代タイムライン分析 (events/timeline.py)
- HTML/Web ビューア、地図表示
- LLM による自然言語レポート生成 (report/narrative.py, 任意機能)
