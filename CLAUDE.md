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
- docs/design/ontology.md — イベントカタログ (設計。現行 v0.2.4)
- **docs/spec/detection.md — 変化検出仕様書 (実装準拠・網羅)。検出ロジックを変更したら必ず同期更新する**

## 現在の状態 (2026-09-22 更新)

roadmap の全マイルストーン (M0〜M10) と主要トラック (V/W3/SD/P/UQ/SP/G/RD4a〜c/IM1) は
**完了**。経緯・完了記録の正は docs/design/roadmap.md、検証ログは docs/verification/、
性能記録は docs/perf/ — このファイルには要約と運用情報のみ置く。

- コア: 検証3フィードで explained_ratio 1.0000、pytest 299件。最大ペア (RawDiff 3万)
  約2秒、国家規模フィード (swiss・ovapi_nl 等) も完走 (docs/perf/P2_*.md)。
  Web の worker は 10240MB/15分、規模ゲート stop_times 200MB/世代 (XL3、
  docs/perf/XL1_lambda_limits.md)
- 出力: HTML レポート (`compare --html` 自己完結 / `--html-lite` / `--html-dir` 分割)、
  AI digest (`--digest*`)、routes.digest.json、mapping.json (ID 対応 — 説明台帳が採択した
  対応のみ)、events/rawdiffs。AI/API 体系の設計は docs/design/ai_interface.md、
  外部向け文書は docs/api/ (README=案内、reference=リファレンス)
- Web 本番: **https://diff.gtfs.jp/** 運用中 (旧 d22mbbm5uatfcc.cloudfront.net も有効。
  DNS はさくら — docs/ops/domain.md)。MCP サーバー https://diff.gtfs.jp/mcp
  (docs/design/mcp.md)。docs/api は /docs/ で配信、開発者向けページ /developers.html
- デプロイ: `cd infra && AWS_PROFILE=AdministratorAccess-948645358251 npx cdk deploy`
  (Docker 必須。SSO 期限切れは `aws sso login --profile AdministratorAccess-948645358251`)
- viewer は viewer/ (Svelte 4 + Vite)。`scripts/build_viewer.sh` で
  src/gtfs_semantic_diff/report/viewer_template.html に同梱 (vitest 組込済み)
- バージョンは CalVer `YYYY.M.D.N` (同日通番付き)

残タスク: XL5 のブラウザ実走目視・XL4 (agency 抽出 — Summit 後判断)・
RD4c-2 (EXP2 エージェント版 A/B 検証)・IM3 (ID 対応の消費者シミュレーション)・
AN1 (Search Console プロパティ確立 — docs/ops/search_console.md、ユーザーアクション含む)・
AN2 (アクセス計測 — docs/ops/analytics.md。GA は見送り、CloudFront ログ + scripts/access_stats.py
の月次集計。初回集計の記録待ち)・RD2 (検証モードの生データ DL)・RD3 (地図リッチ化 — 基図の PMTiles 自前配信
含む)・V6 (運賃深掘り)・SC1〜SC3 (STM 型シーズン同居 — docs/design/scope_and_seasons.md。
STM group46 の self_check 2件はその既知の露頭)。I トラック (国際化) は 2026-09-16 全完了 —
恒常ルールは i18n.md §4。未実装イベント型は detection.md §7 に列挙。

## 過去プロジェクトからの資産移植 (完了)

前身 GTFSDiff リポジトリ (2025、本リポジトリ外) からの移植は M2 で完了。
対応表と移植方針は docs/PORTING.md (以後、旧リポジトリ参照が必要なのは
trip_matcher など「原則不使用」とした部分のみ)。

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
- **過剰適応しない**: 新しい検出・分類規則は (a) 決定的で config 閾値のみ (b) 効かない
  ときは「何もしない」に退化 (誤結合より無動作) (c) 個別フィードの事例に特化しない、
  を満たすこと。データに痕跡のない地域知識 (例: 名古屋守山の補助金由来の route 分割)
  は守備範囲外と明示する — docs/design/route_identity_review.md §4。
- **日付・CalVer 版番号を書く直前に必ず `date` で実時刻を確認する** (継続セッションで
  文書の日付に引きずられた誤記事故の再発防止、2026-08-19)。
- **国際化の恒常ルール (docs/design/i18n.md §4) に従う**: UI 文字列は監査可能な
  辞書/ブロックのみ (ハードコード禁止)、ja 出力不変は機械検査、既存 URL 不変で
  en は併設、機械向けインタフェースは en 一本、JSON は言語中立 (言語別複製なし)、
  データ由来文字列は翻訳しない、通貨・単位はデータから。
- **GTFS-JP 固有フィールドに依存しない**: routes_jp の jp_parent_route_id 等は GTFS-JP の
  今後の改訂で非推奨方向にあるため、データに存在しても同定・分類ロジックの入力には
  使わない。標準 GTFS の内容 (名称・座標・停車列・時刻) から再構成する。
  ※ L0 diff がこれらのファイルを列挙・記帳すること自体は網羅性の要請であり継続する。
- **クライアント側の計測タグ (GA 等) と CLI へのテレメトリは入れない** (2026-09-19
  決定、docs/ops/analytics.md §1): 利用状況はサーバ側ログ (CloudFront 標準ログ・
  MCP 構造化ログ) を集計して把握する。集計出力に IP を含めない。
- **色だけで情報を表さない** (開発者は色弱): レポート・地図・表・UI のすべてで、
  太字・記号 (▲▼・新/廃)・線種・数値を第1チャネルとし、色はその補強に限る。
- 日本語出力が第一級。イベントタイプは英語 ID + 日本語表示名を対で管理 (model/event_types.py)。
- イベントタイプの追加は「残差の精査 → ontology.md への採録 (バージョン注記) →
  event_types.py → ルール実装 + 合成テスト → detection.md 更新」の順で行う
  (例: v0.2.1 の HEADSIGN_CHANGED)。
- 検出ロジック・閾値を変更したら docs/spec/detection.md を同期更新する。
- **表示 (viewer / presentation) の規約を変えたら docs/design/presentation.md の
  PI (表示不変条件) を同期更新し、表示変更の DoD (PI 棚卸し・vitest・検証フィード
  目視) を守る**。便数表記・日付ランの整形は viewer/src/lib/format.js の
  countText / runsText と Python の date_runs_year_split に一元化 —
  表示面ごとの独自整形の追加は禁止 (経緯: docs/design/ui_quality.md)。
  viewer のテストは `cd viewer && npm test` (build_viewer.sh にも組込済み)。
