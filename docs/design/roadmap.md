# ロードマップと Definition of Done

原則: **DoD を満たすまで次のマイルストーンに着手しない。** 「動いた気がする」は完了ではない。

> 状態 (2026-07-07): **M0〜M7・W1・V1〜V5 完了 (V6 は骨格のみ前倒し済み)。
> 次は W3 (Web 公開)。W3-0 (配信基盤) 完了、次は W3-1 (ジョブ API)。**
> 旧 W2 (手動ホスティング) は W3-0 に吸収 (2026-07-07)。X1・V6 本体は並行可。
> 各 DoD の実行結果は docs/verification/ と docs/perf/ に記録済み。
> M0: 673d24e / M1: 036cb0c / M2: 3e04dce / M3: 9168e6f / M4: 7150471 /
> M5: 9733446 / M6: f4cfc6e / M7: f999e2c / W1: 1f62b3d / V1: 81012f3 / V2: 検証ログ docs/verification/V2_presentation_model.md。

## M0: 骨格と読み込み

- model/ のデータクラス定義 (GtfsSnapshot, RawDiff, MatchGraph, ChangeEvent)
- load/: zip 読み込み + calendar→day_type 正規化
- load/repository.py: 旧 `repository.py` を移植し、永井運輸の current / prev_1 を実取得
- DoD: `gtfs-semantic-diff fetch --org nagai-unyu --feed Nagaibus` で2世代の zip がキャッシュされ、Snapshot として読める。pytest 通過。

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
- CLI: `gtfs-semantic-diff compare ... --html out/` (+ 単一ファイルオプション)
- DoD: 検証3フィード (永井 prev_2→prev_1、地鉄 R8、臨港テスト) のレポートを
  ブラウザで開き、**全イベントをクリックすると何らかの詳細が表示される**
  (説明会計の UI 化) ことを目視確認。単一 HTML として保存→再オープンできる。
  地図に停留所異動と shape 新旧が描画される。docs/verification/ に記録。

> W1 のレビューで「内部データ表現がそのまま画面になっている」ギャップが明確になり、
> **Web 化 (W2/W3) は先送り**して、認知単位のレポート再構築 (V1〜V3、設計:
> docs/design/presentation.md) を先に行うことにした (2026-07-05)。

## V1: diff パターンの実例収集と表示要件の確定 【完了 2026-07-06】

- scripts/survey_diff_patterns.py: 80フィードの世代ペアを compare し組合せで機械分類
  (61成功・8類型、docs/verification/V1_pattern_survey.md)。実例ギャラリー16例を生成
- レビュー (07-05〜06) の結果、**スコープを「路線に紐付く変更」に絞って要件凍結**:
  Lev.1〜5 のプレゼンテーションカスケード、出版時刻表形式の新旧差分表示、
  方向グループ (クラスタ由来)、曜日固定順、色弱対応の原則昇格 (R11〜R17)。
  路線に紐付かない変化 (運賃・メタデータ等) の表現は後回しとして明示
- 副産物: 鹿沼市リーバスの組合せ爆発 (性能)、鹿児島市の CSV 引用符エラー (頑健性)、
  explained_ratio < 0.99 ×7フィード (残差カタログ育成の入力) を記録

## V2: プレゼンテーションモデルの生成 (Python 側) 【完了 2026-07-06】

スコープ: **路線 (route_group) に紐付く変更のみ** (presentation.md 凍結要件 R1〜R17)。

- report/presentation.py: events + identity + trip_delta → 路線ページのビューモデル
  - ①路線概要 (系統構成・方向グループ・代表停車列・地図データ)
  - ②変化サマリー: Lev.1〜5 カスケード (吸収規則、Lev.3 影響率、
    Lev.4 = ビン別本数差分の符号別合計、Lev.5 件数集約)
  - ③本数表 (方向グループ→曜日 (固定順)→系統、集計→内訳、変更なし行)
  - ④新旧時刻表: 全パターン停車列の LCS 併合による停留所軸 + trip_delta による
    新旧便対応 (差分表示の素材)。**V2 最大の設計ポイント**
- bundle 拡張: 路線紐付き全 trip の全停留所時刻、全系統のパターン・座標・shape、
  ビューモデル本体。境界閾値 (区間便化昇格・影響率判定) は config へ
- 制約: コア不変・注釈主義 (presentation.md 設計原則 1・2)
- DoD: 3検証フィード + V1 代表実例 (最低: pattern/route_add_drop/service/
  large_revision 型各1) でビューモデルが生成でき、単体テストがある。
  events.json / accounting が W1 時点と互換であることをテストで保証。
  停留所軸併合の合成テスト (途中止まり・経由違い・逆方向)。

## V2.1: 方向グループ規則の一般化 【V3 レビューからの割り込み・完了 2026-07-07】

> **割り込みの経緯と判断**: V3 レビュー第7ラウンドの「地図で上下の線が重なる」問題は
> ビューアのレーン割当変更で症状を解消したが、根本原因は方向グループ形成
> (presentation モデル層) の「端点**完全**逆転 / **完全**一致」要求にあった —
> 実データでは上下便の端点が操車場・営業所・駅前ロータリー分だけずれるのが普通。
> 7フィード実測で **6/7 フィードに系統的な取りこぼし** (逆転43ペア・同方向31ペア。
> 該当ペアの順序整合度は 0.00 / 1.00 に完全に二極化し中間域は0件) を確認し、
> 孤発事例でなくモデル規則の粗さと判断。方向グループはレポートの認知単位 (②〜④の
> 骨格) であり、誤分割のままビューアレビューを進めると V3 レビュー結果が無効化される
> ため、**V3 を一時中断してモデル側を先に修正する** (ビューアで吸収した問題をモデルへ
> 差し戻す)。

- 内容: `_direction_groups` の束ね条件を「停留所集合 Jaccard ≥ 閾値 かつ
  端点完全逆転/完全一致」から「Jaccard ≥ 閾値 かつ **共有停留所の順序整合度**が
  逆転側閾値以下 (往復) / 同方向側閾値以上 (区間便・経由違い)」に置き換える。
  中間域は束ねない (保守的)。leg 割当も代表系統との順序整合度で判定。
  閾値は `[presentation]` (config) に追加
- 変更しないもの: identity 層 (系統=パターンクラスタは方向別のまま)・コア・
  説明会計・JSON イベントスキーマ。束ね範囲も従来どおり route_group ページ内
  (family 跨ぎは従来から起きうる。route_group 跨ぎは起きない)
- 既知の影響: 同方向側の緩和により、端点の異なる区間便群が同一 leg → 同一時刻表に
  併合される (区間外は空欄セル)。出版時刻表の慣行に近づく方向だが表の姿が大きく
  変わるため before/after の目視確認を DoD に含める
- DoD: 合成テスト (非対称往復・区間便併合・循環・中間域の非併合)。検証3フィード
  + V1 代表実例の7フィードで方向グループ数 before/after を記録し、実測で確認した
  取りこぼし (豊前岩屋線・地鉄興人/国立高専線・芦屋22番・八戸4路線) が ⇄ に統合される
  こと、過併合の実例がないことを目視確認。explained_ratio 不変。
  presentation.md R15 の改訂注記と同期。docs/verification/ に記録。

## V3: ビューア再構築 (認知単位 UI) 【完了 2026-07-07 (レビュー合格)】

- 路線ページ4部構成の実装 (presentation.md R1〜R17): ①概要 (地図は折りたたみ) /
  ②Lev サマリー / ③本数表 (数値+記号第1チャネル) / ④出版時刻表形式の
  旧/新/差分3切替 (変更セル太字+記号、廃止列取り消し+「廃」、新設列+「新」)
- **色だけで情報を表さない** (原則5) を全画面で徹底
- イベント羅列・RawDiff・explained_ratio と、路線に紐付かない変化 (運賃等) は
  「検証モード」トグルへ退避 (削除しない)
- DoD: 3検証フィード + V1 代表実例のすべてで新 UI が動作し、ユーザーレビュー合格。
  検証モードから説明会計 (evidence → RawDiff 生値) に到達できることを確認。
  大規模改正例 (八戸) の折りたたみ戦略をレビューで確定。docs/verification/ に記録。
- **達成記録**: レビュー13ラウンド (docs/verification/V3_viewer.md)。途中で
  V2.1 (方向グループ一般化) を割り込み、レポート4部構成・曜日タブ (R18)・
  leg 単位の①・共有停留所ベースの時刻表列ソート等に発展。八戸の折りたたみ戦略 =
  「Lev.1/2 を含むページのみ既定展開 + 曜日タブ + 変更なし路線の別折りたたみ」で確定。
  検証モードは V5 で網羅性ビューに再構築 (説明会計への導線は維持)。
  2026-07-07 ユーザーレビュー合格。

## V4〜V6・X1: 網羅性と路線に紐付かない変化 【計画 2026-07-07 起案、V3 完了後】

設計・課題整理: docs/design/coverage_and_nonroute.md (順序・粒度の論点は
ユーザーレビュー待ち)。「全ての差分を網羅する」原則を UI にも通す一連。

- **V4: 停留所の変化ページ** — D群イベントを停留所クラスタ単位に束ねた人向け章。
  地図 (旧新位置)・影響 route_group との相互リンク。Lev.3 改称注釈も併せて解消。
  DoD: 地鉄 (浜黒崎小学校改称・表町一丁目改称ほか) で停留所章と路線ページの
  相互リンクを目視確認。合成テスト。
  **完了 2026-07-07 (レビュー合格。docs/verification/V4_stop_changes.md)** —
  章 (レポート第2部)・まとめ表示・専用地図・実フィード確認済み。
  ※相互リンクと Lev.3 改称注釈は未実装のまま完了とし、バックログへ移す
  (coverage_and_nonroute.md バックログ参照)。
- **V5: 網羅性ビュー (検証モード再構築)** — 路線単位の羅列を除去し、全イベントを
  「表示先 (路線ページ/停留所ページ/フィード章/どこにも出ない)」で分類。
  presentation_refs (表示単位→消費 event_id) をモデルに追加し、RawDiff→Event→
  表示先の3層トレーサビリティと「レポート被覆率」を出す。
  DoD: 検証3フィードで全イベントに表示先が付き、被覆率が算出される。
  **完了 (2026-07-07、docs/verification/V5_coverage_view.md)** — 検証モードを
  会計サマリー/イベント (表示先別)/ファイル別生差分の3段に全面差し替え。
  表示先は型+subject の決定的対応 (表示単位レベルの refs は将来精緻化)。
  7フィードで被覆率を実測 (地鉄 0.65 — SHAPE_CHANGED 95件が最大の未提示項目
  と判明、次の改善対象)。
- **V6: フィード章 (その他の変化)** — E/F 群 (運賃・有効期間・事業者・曜日区分
  再編・行先表示・翻訳・バリアフリー) の人向け節。V1 で後回しにした
  fare/metadata 主体フィードの章構成をここで解消。
  DoD: V1 ギャラリーの fare 型実例で章が読めることを目視確認。
  **骨格を前倒し実装 (2026-07-07)**: レポートを4部構成に再編 (①フィード全体
  ②停留所 ③路線毎 ④その他 — coverage_and_nonroute.md 参照)。第1部に
  ファイル対応表・期間・曜日別便数・フィード級イベント、第4部に未収載
  イベントの種類別件数 (網羅性の受け皿、V5 で機械的列挙に昇格予定)。
  運賃の料金表 before/after 等の掘り下げは V6 本体で継続。
- **X1: 機械向けインタフェース文書化** (小・随時) — bundle スキーマと
  「AI には events+rawdiffs、表示済み解釈は presentation」の使い分け指針を
  docs/spec/ に明文化。

## M8: 便対応付けの再設計 (trip matching v2) 【完了 2026-07-08 (docs/verification/M8_trip_matching.md)】 (設計: docs/design/trip_matching.md)

- 動機: 八戸の反例で「同一 trip_id の無条件信頼」(tripdelta ②) が連番型 ID
  運用で破綻することを特定 (docs/verification/trip_identity_survey.md)。
  対応付けは C群・B群・churn・④差分時刻表すべての土台であり本質的に解決する
- 内容: ①〜③の4段縦積みを、共有停留所の時刻整合 (Δt_shared)・経路 LCS率・
  ID 一致 (弱い事前) を統合した**コスト最小の大域割当1段**に統一。解く場所は
  コア (tripdelta)。表示層の後付けペアリング (③ _pair_leftovers) は廃止・吸収。
  重み・受理閾値は config [matching]。会計・JSON スキーマ不変
- 手順: 感度分析 (時刻整合を加えた擬似正解でコスト成分の二極化確認・初期重み
  決定) → 実装 (下流 frequency/patterns/technical/presentation の一括移行) →
  評価
- DoD: 合成テスト (連番スライド+経路変更+短縮振替 (八戸型)・ID 全張替え
  (畑線型)・同時刻交差)。クリーン擬似正解での P/R が現行以上。八戸の当該表が
  常識どおりの対応になることを目視確認。8フィードで explained_ratio 不変・
  対応付け before/after を記録。性能を docs/perf に記録。detection.md /
  presentation.md 同期

## M9: family 世代間対応の内容主導化 (route identity v2) 【完了 2026-07-09 (docs/verification/M9_route_identity.md)】 (設計: docs/design/route_identity_review.md)

- 動機: 名古屋市営 (鳴.ワイ→鳴.メグ、route_id 同一の改称が停留所改称と共倒れ) と
  朝日町 (命名規則全面変更+21→9 統合で 29 ページ全て新設/廃止扱い) の反例。
  名前一致を主証拠にする限り改称は原理的に解けない — trip matching v2 の原則
  「名前/ID の一致は弱い事前、内容整合が主証拠」を family linking に適用する
- 内容: I1 停留所クラスタ対応で旧停留所名を翻訳した上での family 停留所集合
  Jaccard による対応付け (N:M 関係、成分サイズ上限で注記に降格、route_id 一致は
  弱い加点)。I2 ページは新世代を背骨に統合 (旧名称注記・類似候補注記)、
  ROUTE_RENAMED/MERGED/SPLIT/RESTRUCTURED を成分の形で発火。
  I3 lev1 便数比率 (新設/廃止ページに落ちた便の割合) を煙感知器メトリクスに。
  route_group / route_family の2層は統合しない (役割宣言を明文化)
- DoD: 合成テスト (停留所改称を伴う路線改称・N:1 統合・成分上限の降格・閾値境界)。
  名古屋 鳴.ワイ→鳴.メグ が1ページ+RENAMED になること、朝日町の lev1 便数比率が
  1.0 から大幅低下することを目視確認。回帰3フィード (徳島・永井・地鉄) で
  explained_ratio 不変。名古屋・朝日町を検証フィードに追加。
  ontology (v0.2.2 ROUTE_RESTRUCTURED)・detection.md・CLAUDE.md 同期

## W3: Web 公開 (ジョブ API + 公開運用) 【着手 2026-07-07】

> 旧 W2 (静的ホスティングの手動運用) は独立マイルストーンとしては廃止し、
> **W3-0 として吸収** (2026-07-07 判断)。手動アップロード運用の確立自体に価値は
> 薄いが、S3+CloudFront の配信基盤はジョブの結果を置く土台そのものなので
> 最初のフェーズとして先に作る。IaC は AWS CDK (Python)、リージョンは
> ap-northeast-1、独自ドメインは後付け (まず CloudFront 既定ドメイン)。

- **W3-0: 配信基盤** 【完了 2026-07-07 (docs/ops/w3_0_delivery.md)】 — S3 (非公開 + CloudFront OAC)・CloudFront・ライフサイクル
  下地・Budgets アラートを CDK で構築。scripts/publish.py (手元生成 HTML の
  アップロード + URL 発行、管理者用・動作確認用)。
  DoD: 検証フィードのレポートが公開 URL (/r/{id}) で第三者環境から閲覧できる。
  手順を docs/ops/ に記録。
- **W3-1: ジョブ API と入力 UI** 【実装・技術検証済み 2026-07-07、ブラウザでのユーザー確認待ち】 — 入力 UI (gtfs-data.jp の事業者・世代セレクタ /
  zip アップロード (上限サイズ、presigned URL))。ジョブ実行: Lambda (コンテナ) +
  API Gateway (非同期投入→ポーリング) + DynamoDB (ジョブ状態)。
  DoD: 公開 URL で 選択/アップロード → 計算 → 閲覧 の一連が動作。
- **W3-2: 公開運用の仕上げ** — Google ログイン (Cognito federation): 匿名 =
  結果30日で自動削除、ログイン = 恒久 URL + アップロード zip 保存。
  フィードバック: 結果ページから {結果URL, event_id, 記述} を記録 + SES 通知。
  コストガード: サイズ上限・レート制限・AWS Budgets (設計: web.md)。
  DoD: 匿名結果の30日削除をライフサイクル設定で確認。フィードバック一連の動作。
  月額コスト実績を docs/ops/ に記録。

## 将来 (スコープ外だが JSON 互換を壊さない)

- report/presentation.py (約1,400行) の3分割 (axis/sheets 系ユーティリティ /
  方向グループ・leg / ページビルダー)。V3 汎用性レビューで「画面要件が動く間は
  見送り」とした件。公開準備 (2026-07-08) 時点でも全テスト緑のため構造変更は
  見送り、次に presentation へ大きな機能を足す直前に実施する
- group 単位の TRIPS_TRUNCATED・family 間振替検出 (M7 の動作実績を見てから)
- 時刻変化の分解精緻化 (一様成分 + 区間残差の合成表現、time_band 次元。
  現状の TIMETABLE_SHIFTED は「±2分程度に収まる小幅な時刻調整」を含む —
  会計上の見落としはなく表現粒度の問題であることを実データで確認済み)
- 多世代タイムライン分析 (events/timeline.py)
- LLM による自然言語レポート生成 (report/narrative.py, 任意機能)
