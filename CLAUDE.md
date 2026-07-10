# gtfs-semantic-diff — GTFS 意味的差分抽出ツール

複数世代の GTFS フィードを比較し、変化を「人間が認識できる意味」(路線廃止、減便、区間短縮、乗り場変更など)として抽出・レポートする CLI ツール。GTFSデータリポジトリ (https://gtfs-data.jp) の世代管理 API と連携する。

## 最重要設計原則

1. **説明台帳 (explanation ledger)**: L0 で検出した生差分(全ファイル・全フィールド)は、必ずいずれかの ChangeEvent の `evidence` に紐づくか、`UNEXPLAINED_RESIDUAL` としてレポートされる。**網羅性はこの台帳で構造的に保証する。** 被覆率(explained ratio)は常に計測・表示する。(旧称「説明会計 (explanation accounting)」を 2026-07-10 に改称。JSON キー `accounting`・モジュール名 `events/accounting.py` 等のコード識別子は安定インタフェースのため旧称のまま)
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

必読ドキュメント:
- docs/design/architecture.md — モジュール構成と JSON スキーマ
- docs/design/ontology.md — イベントカタログ (設計。現行 v0.2.2)
- **docs/spec/detection.md — 変化検出仕様書 (実装準拠・網羅)。検出ロジックを変更したら必ず同期更新する**

## 現在の状態 (2026-07-11)

roadmap M0–M9 **全完了**。検証3フィードで explained_ratio 1.0000、pytest 167件、
性能は最大ペア (30,700 RawDiff) で約2秒 (docs/perf/M5_timings.md)。
検証ログは docs/verification/ (M2〜M9)。未実装項目は detection.md §7 に列挙
(THROUGH_SERVICE、TIME_BAND_VARIANT、DWELL_TIME、多世代タイムライン等)。
M8 (trip matching v2): 便対応は内容主導のコスト最小割当 (ID は弱い事前)。
M9 (route identity v2): family 世代間対応も内容主導 (停留所翻訳+集合 Jaccard、
N:M 成分 → RENAMED/MERGED/SPLIT/RESTRUCTURED、ページは新世代背骨+旧名称注記、
lev1_trip_ratio を煙感知器に) — docs/design/route_identity_review.md。
M10 (day_type 精密化): 曜日指定は dow_XXXXXXX として一級化 (「特定日」の実態は
83%が規則的な曜日指定運行)、運行日ゼロは inactive、特定日の内訳 (置き換え/追加)
を第1部に表示 — docs/design/day_types.md。
route_group (枝番系統の「路線ブランド」集約) も M7 で実装済み —
仕様は docs/design/route_group.md と detection.md §2.5。
HTML レポート: `gtfs-semantic-diff compare --html out.html` (自己完結・単一ファイル、W1)。
ビューアは viewer/ (Svelte 4 + Vite)、ビルド成果物を
src/gtfs_semantic_diff/report/viewer_template.html に同梱 (再ビルド: scripts/build_viewer.sh)。
**現在の作業トラック: Web 公開 (roadmap W3、設計: docs/design/web.md)。**
V トラック (認知単位のレポート再構築 V1〜V5) は 2026-07-07 に完了:
レポートは4部構成 (①フィード全体 ②停留所 ③路線毎 ④その他) + 曜日タブ +
検証モード=網羅性ビュー (レポート被覆率・ファイル別生差分)。要件は
presentation.md R1〜R18 (凍結+改訂履歴)。コア・JSON スキーマ・説明台帳は不変。
W3 は W3-0 (S3+CloudFront 配信基盤、CDK Python、ap-northeast-1) と W3-1
(Lambda ジョブ API + 入力 UI) が完了、W3-2 (ログイン・保存ポリシー・フィード
バック・コストガード) は**方針確定済み** — docs/design/w3_2_directions.md
(アカウント=Google のみ+内部 user_id、結果 URL=uid ベース正準+不変版管理、
zip 保存・再利用、ログ研究利用の同意)。旧 W2 は W3-0 に吸収。
バージョンは CalVer `YYYY.M.D.N` (同日通番付き、2026-07-11〜)。
V6 本体 (運賃深掘り)・X1 (bundle スキーマ文書化) は並行可能な残タスク。**

## 過去プロジェクトからの資産移植 (完了)

前身: 2025年の GTFSDiff リポジトリ (ローカル参照のみ・本リポジトリ外)。
M2 で移植完了 — pattern_clustering / route_analyzer (Family 抽出部) / stop_analyzer
(2段階クラスタリング部) / repository.py。対応表と移植方針は docs/PORTING.md。
以後、旧リポジトリを参照する必要が生じるのは trip_matcher など「原則不使用」とした部分のみ。

## gtfs-data.jp API メモ (2026-07 動作確認済み)

- Base: `https://api.gtfs-data.jp/v2`
- `GET /feeds?pref=<id>` / `GET /feeds?org_id=<id>` — フィード一覧
- `GET /organizations/{org_id}/feeds/{feed_id}?max_prev=N` — 世代付きファイル一覧
- RID 体系: `current`, `prev_1`, `prev_2`, …

## 検証フィード (回帰テストの基準)

1. 永井運輸 `nagai-unyu / Nagaibus` (API・小規模)。基準ペア prev_2→prev_1
   (2025-10-01 改正: 運賃改定・ココルンシティ乗り入れ・表町一丁目改称)
2. 富山地方鉄道バス `chitetsu / chitetsubus` (API)。基準ペア prev_2→prev_1
   (令和8年4月1日改正: フィーダーバス水橋延伸・浜黒崎小学校改称・ぶりかにバス終了)
   ※ rid は世代が進むとずれるため、有効期間 (from_date) で当該改正ペアを特定し直すこと
3. 川崎鶴見臨港バス (ローカル zip)。`~/Downloads/gtfs-臨港テストデータ(*).zip` を
   data/ にコピーして使用 (ダイヤ01 が基準、系統路線増減/増便減便/ダイヤ時分変更01 と比較)
4. 名古屋市営バス (ローカル zip、data/nagoya/)。20250329→20260328
   (M9 基準: 鳴.ワイ→鳴.メグ の route_id 同一改称 + 停留所改称の共倒れ回避。
   lev1_trip_ratio 0.0)
5. 朝日町 `toyama-asahitown / asahimachibus` (API)。基準ペア prev_1→current
   (M9 基準: 命名規則全面変更+21→9 路線統合。9ページ・RENAMED 2 + MERGED 7・
   lev1_trip_ratio 0.0。宮崎境線↔市振線のコリドー連鎖 → best-match 間引きの実例)

## 開発環境

- venv は **`.venv.nosync`** に作る (`uv venv .venv.nosync --python 3.14` →
  `ln -s .venv.nosync .venv`)。リポジトリが iCloud 同期下にあり、`.venv` 直下だと
  site-packages の .pth に hidden フラグが復元され続け Python 3.14 が無視して壊れる。
  `.venv` シンボリックリンクも iCloud に消されることがあるため、コマンドは
  `.venv.nosync/bin/...` を直接使うのが確実。
- テスト: `.venv.nosync/bin/python -m pytest -q` / リント: `.venv.nosync/bin/ruff check src tests`
- 生成物 (events.json 等) は data/ へ (gitignore 済み)

## 開発ルール

- マイルストーンと Definition of Done は docs/design/roadmap.md に従う。**DoD を満たすまで次のマイルストーンに着手しない。**
- 「完了」と記録してよいのは、検証フィードでの実行結果を確認したときのみ。
- 各 ChangeEvent ルールには必ず: 検出条件のドキュメント、合成 GTFS による単体テスト、実フィードでの目視確認例、の3点を付ける。
- 閾値(距離、類似度、時間帯ビン等)は `config/default.toml` に集約。コード内リテラル禁止。
- **GTFS-JP 固有フィールドに依存しない**: routes_jp の jp_parent_route_id 等は GTFS-JP の
  今後の改訂で非推奨方向にあるため、データに存在しても同定・分類ロジックの入力には
  使わない。標準 GTFS の内容 (名称・座標・停車列・時刻) から再構成する。
  ※ L0 diff がこれらのファイルを列挙・記帳すること自体は網羅性の要請であり継続する。
- **色だけで情報を表さない** (開発者は色弱): レポート・地図・表・UI のすべてで、
  太字・記号 (▲▼・新/廃)・線種・数値を第1チャネルとし、色はその補強に限る。
- 日本語出力が第一級。イベントタイプは英語 ID + 日本語表示名を対で管理 (model/event_types.py)。
- イベントタイプの追加は「残差の精査 → ontology.md への採録 (バージョン注記) →
  event_types.py → ルール実装 + 合成テスト → detection.md 更新」の順で行う
  (例: v0.2.1 の HEADSIGN_CHANGED)。
- 検出ロジック・閾値を変更したら docs/spec/detection.md を同期更新する。
