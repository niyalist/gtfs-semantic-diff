# ロードマップと Definition of Done

原則: **DoD を満たすまで次のマイルストーンに着手しない。** 「動いた気がする」は完了ではない。

> 状態 (2026-07-04): **M0〜M7 完了。** 各 DoD の実行結果は docs/verification/ と
> docs/perf/ に記録済み。M0: 673d24e / M1: 036cb0c / M2: 3e04dce / M3: 9168e6f /
> M4: 7150471 / M5: 9733446 / M6: f4cfc6e / M7: 完了 (docs/verification/M7_route_group.md)。
> **M0〜M7 完了。以降は「将来」節が作業対象。**

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

## M7: route_group 実装 【完了 2026-07-04】

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

## W1: 結果バンドル + HTML ビューア 【完了 2026-07-04 (レビュー 2026-07-05)】 (設計: docs/design/web.md)

- report/bundle.py: ビューア用結果バンドル書き出し (events.json / rawdiffs.json /
  geometry.geojson (停留所座標・shape 新旧) / timetables.json / meta.json)
- viewer/ (Svelte + Vite): 概要 → クリックでドリルダウンの SPA。
  イベント種別に応じた詳細パネル (時刻表 before/after、MapLibre 地図、
  evidence の生値テーブル)。残差もクリック可能。単一 HTML ファイル出力対応
- model/event_types.py に display_name_en を追加、UI 文字列の ja/en 切替
- CLI: `gtfs-semdiff compare ... --html out/` (+ 単一ファイルオプション)
- DoD: 検証3フィード (永井 prev_2→prev_1、地鉄 R8、臨港テスト) のレポートを
  ブラウザで開き、**全イベントをクリックすると何らかの詳細が表示される**
  (説明会計の UI 化) ことを目視確認。単一 HTML として保存→再オープンできる。
  地図に停留所異動と shape 新旧が描画される。docs/verification/ に記録。

> W1 のレビューで「内部データ表現がそのまま画面になっている」ギャップが明確になり、
> **Web 化 (W2/W3) は先送り**して、認知単位のレポート再構築 (V1〜V3、設計:
> docs/design/presentation.md) を先に行うことにした (2026-07-05)。

## V1: diff パターンの実例収集と表示要件の確定

- scripts/survey_diff_patterns.py (読み取り専用): gtfs-data.jp から世代ペアを
  サンプリングして compare を回し、変化の組合せで機械分類する
  (便数系のみ / 停車パターン変化あり / 路線増減 / 停留所再編 / カレンダー系のみ /
  運賃のみ / 大規模改正 など)
- 各類型の代表フィードで HTML レポートを生成し「実例ギャラリー」として提示 →
  ユーザーレビューで表示要件を収集し presentation.md の要件表 (R11..) に追記
- DoD: 類型分類と代表実例の一覧が docs/verification/ に記録され、
  presentation.md の要件表と未確定事項がユーザーレビューを経て**凍結**されている
  (V2 実装中の要件変更を原則しない状態にする)。

## V2: プレゼンテーションモデルの生成 (Python 側)

- report/presentation.py: events + identity + trip_delta → 認知単位のビューモデル
  (①路線概要 / ②本数マトリクス (集計→内訳・変更なし行・増減量) /
  ③方向×曜日単位の時刻表比較 + シフト特徴注釈 (一様成分+区間残差、表示用) /
  ④パターン変化の統合ユニット)
- bundle 拡張: 全系統の概要データ (パターン・座標・便数)、全グループの時刻表、
  プレゼンテーションモデル本体を同梱
- 制約: コア (L0/L1/L2・ChangeEvent スキーマ・説明会計) は変更しない。
  注釈は新イベントタイプにしない (presentation.md 設計原則)
- DoD: 3検証フィード + V1 代表実例でビューモデルが生成でき、単体テストがある。
  events.json / accounting が W1 時点と互換であることをテストで保証。

## V3: ビューア再構築 (認知単位 UI)

- ①〜④の画面実装 (presentation.md の骨格と R1〜 の要件に従う)。
  イベント羅列・RawDiff・explained_ratio は「検証モード」トグルへ退避 (削除しない)
- DoD: 3検証フィード + V1 代表実例のすべてで新 UI が動作し、ユーザーレビュー合格。
  検証モードから説明会計 (evidence → RawDiff 生値) に到達できることを確認。
  docs/verification/ に記録。

## W2: 静的ホスティング (手動運用) 【V3 完了後に再開】

- S3 + CloudFront + 独自ドメイン + HTTPS。結果バンドルを手動アップロードし
  恒久 URL (/r/{id}) で共有する運用手順を確立
- DoD: 第三者環境 (別ネットワーク・スマホ含む) で公開 URL の閲覧を確認。
  手順を docs/ops/ に記録。

## W3: ジョブ API と公開運用 【V3 完了後に再開】

- 入力 UI: gtfs-data.jp の事業者・世代セレクタ / zip アップロード (上限サイズ)
- ジョブ実行: Lambda (コンテナ) + API Gateway (非同期投入→ポーリング) + DynamoDB
- Google ログイン (Cognito federation): 匿名 = 結果30日で自動削除、
  ログイン = 恒久 URL + アップロード zip 保存
- フィードバック: 結果ページから {結果URL, event_id, 記述} を記録 + SES 通知
- コストガード: サイズ上限・レート制限・AWS Budgets アラート (設計: web.md)
- DoD: 公開 URL で一連 (選択/アップロード → 閲覧 → フィードバック) が動作。
  匿名結果の30日削除をライフサイクル設定で確認。月額コスト実績を docs/ops/ に記録。

## 将来 (スコープ外だが JSON 互換を壊さない)

- group 単位の TRIPS_TRUNCATED・family 間振替検出 (M7 の動作実績を見てから)
- 時刻変化の分解精緻化 (一様成分 + 区間残差の合成表現、time_band 次元。
  現状の TIMETABLE_SHIFTED は「±2分程度に収まる小幅な時刻調整」を含む —
  会計上の見落としはなく表現粒度の問題であることを実データで確認済み)
- 多世代タイムライン分析 (events/timeline.py)
- LLM による自然言語レポート生成 (report/narrative.py, 任意機能)
