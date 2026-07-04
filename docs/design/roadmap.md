# ロードマップと Definition of Done

原則: **DoD を満たすまで次のマイルストーンに着手しない。** 「動いた気がする」は完了ではない。

> 状態 (2026-07-04): **M0〜M6 完了。** 各 DoD の実行結果は docs/verification/ と
> docs/perf/ に記録済み。M0: 673d24e / M1: 036cb0c / M2: 3e04dce / M3: 9168e6f /
> M4: 7150471 / M5: 9733446 / M6: 調査ログ docs/verification/M6_route_group_survey.md。
> **次は M7 (route_group 実装)。**

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

## M6: route_group 横断調査 【完了 2026-07-04】 (設計: docs/design/route_group.md)

- 動機: 枝番系統 (30A/30B/… 前橋玉村線) が別 family になりレポートの納得感を欠く問題。
  family の上に「路線ブランド」集約層を足す前に、シグナルと閾値を実データで裏付ける
- scripts/survey_route_groups.py (読み取り専用): gtfs-data.jp 80 フィードで
  集約率分布・語幹一致対の停留所 Jaccard 分布・誤結合実例・分割候補頻度を計測
- **GTFS-JP 固有フィールド (routes_jp / jp_parent_route_id 等) は調査対象にも判定材料にも
  しない** (CLAUDE.md 開発ルール参照)
- DoD 達成: docs/verification/M6_route_group_survey.md に記録。
  **主要な発見: 停留所 Jaccard の AND ゲートは棄却** (枝番系統は別コリドーが普通、
  30A/30B の共通停留所は1つ)。グループ化は語幹一致のみ + 語幹品質ガード
  (最小長・ストップワード)、Jaccard は凝集度メタデータとしてレポートに明示する
  仕様に確定し route_group.md へ反映済み。

## M7: route_group 実装

- identity/route_group.py: 語幹一致による family のグループ化 (M6 で確定した仕様:
  NFKC + 先頭コード除去 + 最小長/ストップワードガード。停留所 Jaccard はゲートに使わず
  凝集度メタデータとして算出)
- events: subject に route_group を追加 (additive)。context.band_profiles にも併記
- report: 路線別章を route_group 単位に変更 (group 内は family / 方向 / パターンの内訳を維持、
  章冒頭に構成 family と凝集度を明示)
- report: **低凝集 family の小見出し分割** (M6 発見 4 の分割方向): family 内の
  パターンクラスタ間凝集度が low_cohesion_note を下回る場合、パターンクラスタ単位の
  小見出しに分割 (例: 琴参バス美合線 → 本線 / 落合橋接続の区間便)
- DoD: 永井運輸で 30A〜30K 前橋玉村線が1章に集約され、富山地鉄・臨港で誤結合ゼロを
  目視確認。分割方向は美合線型の実例 (M6 調査フィード) で小見出し分割を目視確認
  (docs/verification/ に記録)。explained_ratio が M5 水準を維持。
  合成 GTFS の単体テスト (結合・非結合・語幹衝突・低凝集分割の4ケース以上)。

## 将来 (スコープ外だが JSON 互換を壊さない)

- group 単位の TRIPS_TRUNCATED・family 間振替検出 (M7 の動作実績を見てから)
- 多世代タイムライン分析 (events/timeline.py)
- HTML/Web ビューア、地図表示
- LLM による自然言語レポート生成 (report/narrative.py, 任意機能)
