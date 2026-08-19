# AI 向けインタフェース (RD4) — 設計

2026-08-19 起案。roadmap RD4 (AI digest) の具体設計。X1 (機械向けインタフェース
文書化) を本トラックに併合する (成果物: docs/api/)。
方針の原点は docs/design/report_delivery.md §4 (「事実は digest、文章化は外部
LLM。ツール本体に LLM は入れない (設計原則4)。digest → MCP の順に育てる」)。

## 1. 目的とユースケース

形式的に抽出した差分を AI が意味解釈し、次のアクションに繋げられるようにする:

- **(a) エラーチェック**: データ作成者が残差・ID 張り替え・怪しいパターンから
  入力データの誤りを見つける。狭く深い情報 (どの行か = ID) が要る。
- **(b) 人間語への翻訳**: 「駅と市街地を結ぶ便が減った」のような告知文・
  解説の生成。広く浅い情報 (路線名・便数・時間帯)。ID は雑音。
- **(c) 研究**: 減便・路線再編の地域横断・時系列分析。集計値と来歴。

3者は必要な「深さ×広さ」が違うため、単一の静的ファイルでは満たせない。

## 2. 原理

1. **階層は人間 UI と同型にする。** LLM のコンテキスト窓は人間の画面・注意力と
   同じ制約であり、解も同じ: 第1部 (全体) → 第3部 (路線毎の要約行) →
   便レベル → 検証 (残差)。AI 向けに新しい情報設計は発明しない。
2. **数値一致不変条件 (PI-1 の拡張)**: digest が言う便数・件数は、人間向け
   レポート (presentation/accounting) と一致する。人と AI が違う数字を
   言わないこと。実装上、digest は bundle の**もう一つのレンダラ**として作る
   (コア不変・設計原則3と整合)。
3. **ID は階層で出し分ける**: L0 = ID なし (名前と数値のみ) / L1 = trip_id
   旧新・service_id (ソースに戻れるポインタ) / L2 = 完全キー (既存の
   events/rawdiffs)。説明台帳の思想 (全主張は証拠に遡れる) を AI 出力にも通す。
4. **省略は明示する**: 分量制御は階層化+部ごとの上限で行い、上限で切った
   ことと全量の所在 (L1/L2) を必ず記す。silent truncation はしない。
5. **LLM はコアに入れない** (設計原則4)。digest は決定的な事実の投影。

## 3. 3層の仕様

### L0: 全体 digest (`--digest out.md` / `--digest-json out.json`)

数十〜数百 KB。内容 (人間 UI の部構成と対応):

- **ヘッダ (来歴)**: ツール版・スキーマ版・org/feed・新旧の uid・有効期間・
  世代規則 (GENERATION_SCOPE)・比較実行日時。
- **総括**: 路線数/便数 (day_type 別・1日あたり、旧→新)、explained_ratio、
  イベント種別×件数表 (出現した型のみ。44種の型 ID は docs/api/reference.md)。
- **第2部相当**: 停留所の変化一覧 (改称・新設・廃止・移設。名前ベース)。
- **第3部相当**: 路線 (route_group ページ) 毎に 1〜3行 —
  ページ名・方向と便数 (旧→新、day_type 別)・変化タグ (page digest の
  kind+trips を文章化: 経由変更4便、時刻変更1便 等)・severity 最大値・
  RENAMED/MERGED 等の同定イベント・特定日の注記。
- **第4部相当**: 路線に紐付かない変化 (運賃・カレンダー・メタデータ)。
- **検証サマリ**: 残差の (file, kind) 別件数、TECHNICAL_ID_CHURN 件数、
  self_check 結果。

形式は Markdown と JSON の2形式を同一素材から生成する。Markdown は見出し
構造を固定 (機械的に節を切り出せる)。表は件数表のみに使い、便・停留所の
列挙は箇条書きレコードにする (幅のある表は LLM も人も読み誤る)。

### L1: 路線詳細 (`--digest-route <ページ名>` / 将来は MCP ツール)

1路線分。**変化のある便は全レコード、無変化・ID のみ変更は件数に畳む**:

```
- 7:10発 → 8:35着 [経由変更] 旧: 上土方落合経由 → 新: アイク前・二軒屋橋経由
  (trip 1234→5678, service WD)
- 9:00発 [時刻変更] 3停留所で +5分 (trip 2345→2345)
- 11:30発 [廃止] (trip 3456)
- ほか無変化 4便
```

停車列の変化 (追加/削除された停留所)、特定日の内訳 (運行日ラン) を含む。
時刻の全量マトリクス (④の見た目) は出さない — 必要なら L2 へ。

### L2: 検証層 (既存資産)

events.json (ChangeEvent 全件+evidence)・rawdiffs.json (L0 生差分全件)。
RD2 で版と並置済み (`r/{pair}/v/{版}.events.json` 等)。新規実装なし、
X1 = スキーマの文書化のみ (docs/api/reference.md)。

## 4. 言語

digest.md は日本語先行 (国内利用が第一級)。JSON はキー英語・イベント型は
type_id (英語 ID) + display_name_ja/en の対 (既存 event_types と同じ構造) で、
I トラック (JSON 言語中立化) と矛盾しない。

## 5. API 体系 (2026-08-19 全面見直し — 外部システムのバックエンド化)

ID 対応 (mapping) の追加を機に体系を再点検した。結論: 「版付き静的成果物+
薄い動的層」の骨格は維持。欠落していたのは以下で、これを体系の背骨にする。

### 5.1 提供物の全体像 (層と契約)

| 層 | 成果物 | 契約 |
|---|---|---|
| 安定 | events.json / digest.md・json (L0) / **routes.digest.json (L1 全路線)** / **mapping.json (ID 対応)** / 台帳・URL 規則 | schema 版付き、変更は追記的。docs/api が正 |
| 内部 | bundle (`v/{版}.json`) | ビューア専用。予告なく変わる |
| 動的 | /api/jobs・/api/gtfs (将来: MCP) | 薄い層。実体は静的成果物 |

- **routes.digest.json**: 全路線の L1 を route_group 名キーの1オブジェクトに
  束ねる (per-route URL は日本語名のエンコード地獄になるため不採用)。
  L1 には③相当の**時間帯別本数** (band_matrix の aggregate/leg 行) と、
  構成 family の **route_id 旧/新リスト** (軽注記) を含める — EXP2 部分再現
  6件のうち時間帯系 (CHI-04 型) を解消する。
- **mapping.json (IM トラック)**: identity 層 (MatchGraph + family_components +
  TripDelta) の直接の直列化。stops (クラスタ対応 = platform_ids で GTFS
  stop_id 群の旧新対応、改称・移設距離)、routes (family 対応 = route_ids
  旧新、relation: continued/renamed/merged/split/restructured/added/removed、
  confidence)、trips (exact/churn/modified/removed/added)、day_types。
  **N:M は配列のまま渡し 1:1 に潰さない。confidence と関連イベントへの
  参照を必ず付ける** (説明台帳の思想の ID 版)。判断 (移設200mを同一と
  扱うか等) は消費側に残す。用途: 乗客データの経年結合、shapes 等の
  整備資産の世代引き継ぎ、サイネージ設定移行。
  注意: identity アルゴリズム改良でツール版が上がると対応結果も変わり得る
  (版で再現可能・消費側は版をピン) — この契約を docs/api に明記する。

### 5.2 発見と台帳 (URL 規則を「知識」から「データ」へ)

```
llms.txt → フィード台帳 → ペア台帳 (マニフェスト) → 各成果物
```

- **ペア台帳 = マニフェスト化**: index.json の versions[] に artifacts{}
  (成果物名 → url・gzip・schema) を持たせ、拡張子規則の暗記を不要にする。
- **フィード台帳 (新設)**: `feeds/{org}__{feed}.json` — このフィードで
  計算済みのペア一覧 (uid・from_date・latest 版)。経年利用 (mapping の
  隣接連鎖) と MCP find 系の入口。ジョブ完了時に read-modify-write
  (ペア台帳と同じ楽観方式)。
- **latest エイリアスの一般化**: `r/{pair}.digest.md|json` に加え
  `.routes.digest.json` / `.mapping.json` も。
- digest.md の末尾に深掘り節 (meta.raw_urls の実 URL) — L0→L1→L2 を自走可能に。

### 5.3 周辺整備

- **RID 指定のジョブ投入**: `{"org","feed","old_rid":"prev_1","new_rid":"current"}`
  を受けサーバーで uid 解決 (フル uid 指定も従来どおり)。
- **docs/api のサイト配信**: `/docs/README.md`・`/docs/reference.md`。
  llms.txt から参照。
- **成果物 GET に CORS**: ブラウザアプリ (shapes エディタ等) からの直接
  fetch を許す。

## 6. MCP (RD4c、将来)

> **2026-08-19**: 実装可能な粒度の設計は docs/design/mcp.md に精緻化した
> (ツールセット・トランスポート・検証計画・段階)。以降の正はそちら。

配信基盤 (RD1b/RD2) が既に版付き・immutable の機械可読 API になっているため、
MCP サーバーはそれを取得する stateless な薄い層として実装できる。ツール構成案:

```
find_feeds(pref|org) / find_generations(org, feed)   # gtfs-data.jp プロキシ (既存 /api/gtfs/*)
run_compare(org, feed, old_uid, new_uid)             # 既存ジョブ API。コストガード連動が先行条件
get_digest(pair)                                     # L0
get_route_detail(pair, route)                        # L1
get_stop_changes(pair) / get_residuals(pair)         # L0 の節の単体取得
get_events(pair, type?, route?)                      # L2 のフィルタ取得
```

先行条件: run_compare は課金計算を伴うため W3-2c のコストガード・認可設計を
MCP 経由にも通すこと。digest (RD4a) の内容設計がそのままツール応答の設計になる
ため、実装順は files → Web 並置 → MCP とする。

## 7. マイルストーン

- **RD4a: digest 出力** 【実装 2026-08-19 (report/digest.py)】 —
  `--digest` / `--digest-json` / `--digest-route`。
  数値一致不変条件は tests/test_digest.py で機械検査 (accounting 透過・
  イベント件数合計・便数の feed_overview 一致・L0 に trip_id が現れない・
  L1 の便の保存則)。スキーマは docs/api/reference.md §7 (X1 併合)。
  目視: 掛川 (経由変更・時刻変更が L1 で trip_id 付きレコード化)、
  永井 (2025-10-01 改正の運賃改定・ココルンシティ乗り入れ・表町一丁目改称が
  L0 だけで判読可能)。EXP2 の判定シート68項目の再現検証も完了 (2026-08-19):
  62項目完全再現・6項目部分 (根拠の一部が L2)・判定逆転 0 —
  docs/verification/RD4a_exp2_digest.md。§4 停留所リストの上限
  (digest_stops_max) はこの検証での実害 (SUWA 261件) を受けた追補。
- **RD4b: Web 並置** 【実装 2026-08-19】 — `r/{pair}/v/{版}.digest.md|json`
  を RD2 と同じ棚に (Lambda worker が同じ bundle から生成 = 数値一致、
  gzip なしの素置き、immutable。アップロード由来も並置)。meta.raw_urls に
  digest の URL も焼き込み (additive)。URL を LLM に渡すだけで使える。
  **追補 (2026.7.30.3、発見導線)**: レポート HTML の head に
  link rel=alternate、最新版エイリアス r/{pair}.digest.md|json
  (.html を置換するだけの規則)、index.json versions[] に digest キー、
  /llms.txt (サイト全体の機械向け案内) — 「結果 URL を AI に投げる」
  フローで digest に到達できる。
- **RD4c-0: routes.digest.json + 台帳強化** 【実装 2026-08-19、本番検証済み】 —
  L1 全路線束ね (時間帯別本数・route_id 軽注記込み)、ペア台帳の
  マニフェスト化、フィード台帳、latest エイリアス一般化、digest.md
  深掘り節、RID 投入 (既存実装の文書化)、docs 配信、CORS (§5)。
- **IM1: mapping.json** 【実装 2026-08-19。検証: docs/verification/
  IM1_mapping.md — 永井で公式発表と完全一致、朝日町で N:1 保持】 —
  identity 層の直列化 (§5.1)。**採択された対応のみ** (同名継続+
  STOP_RENAMED 採択対+M9 成分。MatchGraph の仮説エッジは棄却済み対応を
  含むため出さない — 実装時に永井で偽対応混入を検出して確定した規則)。
  CLI `--mapping`、Web 並置、合成テスト (改称・churn・N:M)、docs/api §8。
- **IM2/IM3 (後続)**: 消費者シミュレーション検証 (合成乗降データの世代跨ぎ
  結合で件数保存を機械検査)・実フィード錨 (名古屋 鳴.ワイ→鳴.メグ、
  朝日町 21→9 統合の N:1)。論文の応用節候補。
- **RD4c-1: MCP サーバー** 【設計 2026-08-19 (docs/design/mcp.md)、実装未着手】
  — RD4c-1a (読み取り系+contract test) → RD4c-1b (run_compare) →
  RD4c-2 (EXP2 エージェント版 A/B 検証)。

## 8. 決定事項・棄却案

- L1 は「変化のみ全量+無変化は件数」(決定)。全便の時刻マトリクスは出さない
  (幅のある表は AI にも不向き。全量が要る用途は L2 が既に担う)。
- presentation (bundle) を AI の一次入力にはしない — 視覚投影 (停留所軸・
  分冊・レーン) が冗長で、スキーマ安定性も保証しない (schema_version は
  ビューア同梱で回る)。安定インタフェースは events + digest。
- HTML の単純 Markdown 化 (棄却): 視覚のための構造をテキストに落としても
  AI の役に立たず、数値一致の保証もない。
