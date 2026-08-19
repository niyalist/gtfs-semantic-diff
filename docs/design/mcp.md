# MCP サーバー (RD4c-1) — 設計

2026-08-19 起案。ai_interface.md §6 の構想を実装可能な粒度に精緻化する。
実装は未着手 — 本文書はその前提となる設計の正。

## 1. 位置付けと投資判断

RD4a〜RD4c-0/IM1 で、システムは既に **HTTP+静的成果物として完全に機械可読**
(llms.txt → フィード台帳 → ペア台帳 artifacts → digest/routes/mapping/events)。
MCP がそこに上乗せするのは2つだけで、それ以外を目的にしない:

1. **多段ワークフローの型付け**: 探索→世代選択→比較実行→ポーリング→
   digest→深掘り、の連鎖。URL fetch 型エージェントは GET は得意でも
   POST+ポーリング+URL 組み立ての連鎖で迷子になる。
2. **クライアント到達性**: claude.ai / Claude Desktop / ChatGPT 等の
   非開発者が「コネクタ登録するだけ」で使える。アプリ内ブラウザの
   ドメイン許可機構 (2026-08-19 の ChatGPT デスクトップの事例 — サーバー側は
   全開でもクライアント側ポリシーで fetch が止まる) を経由しない到達経路。

**原則: 薄いアダプタ。** ロジック・ストレージ・新データ経路を一切持たず、
既存の公開 HTTP 面 (ジョブ API + 版付き成果物) を呼ぶだけの変換層にする。
安定層はあくまで HTTP+静的成果物であり、MCP が落ちても何も失われない。
プロトコル仕様の変化はアダプタの作り直しで吸収する (資産は無傷)。

## 2. トランスポート・ホスティング

- **Streamable HTTP / stateless** (リモート向けの現行推奨トランスポート。
  旧 HTTP+SSE は採らない)。セッション状態を持たないので
  API Gateway + Lambda にそのまま載る。
- 配置: 既存スタックに `/mcp` ルートを1つ追加 (CloudFront →
  API Gateway → 既存 api Lambda に同居 or 専用 Lambda。イメージは共用)。
- **公式 Python SDK を使い、プロトコルは手書きしない**。SDK はピン留めし、
  更新はプロトコル非依存の contract test (下記 §6) の通過で受け入れる。
- ⚠ **着手時に最新の MCP 仕様・SDK を必ず確認する** (仕様は年数回改訂される。
  本設計の記述は 2026-08 時点の理解で、トランスポート名・認可仕様は
  着手時に照合してから書く)。

## 3. ツールセット

読み取り系はすべて既存成果物の取得+切り出し。応答は digest と同じ規律
(上限+省略の明示+全量への URL ポインタ) に従う。

| ツール | 実体 | 備考 |
|---|---|---|
| `find_feeds(pref?, org?, query?)` | /api/gtfs/feeds | フィード探索 |
| `find_generations(org, feed)` | /api/gtfs/files | uid・from_date 一覧 |
| `list_pairs(org, feed)` | フィード台帳 | 計算済みペア+隣接連鎖 |
| `run_compare(org, feed, old, new)` | POST /api/jobs | old/new は uid でも rid でも。既存コストガードを通る。応答は job_id+status+成果物 URL |
| `get_job_status(pair)` | GET /api/jobs/{pair} | ポーリング用 |
| `get_digest(pair)` | digest.md (最新版) | L0 をそのまま (md が LLM の一次資料) |
| `list_routes(pair)` | digest.json routes | 路線名+変化タグの一覧 (L1 の目次) |
| `get_route_detail(pair, route)` | routes.digest.json の1キー | L1。md 整形して返す |
| `map_ids(pair, stop_id?, route_id?, trip_id?, name?)` | mapping.json の点引き | ID/名前から対応エントリを検索。IM の対話面 |
| `get_stop_changes(pair)` / `get_residuals(pair)` | digest.json の節 | 第2部/検証サマリ単体 |
| `get_events(pair, type?, route?, severity?, limit=50)` | events.json フィルタ | L2。超過は件数明示+URL |

- pair は `run_compare`/`list_pairs` の応答に含めて受け渡す (クライアントに
  URL 規則を意識させない)。
- ツール説明文に利用原則を埋め込む: 「数値は再計算しない」「省略表示の
  全量は JSON 版」「mapping の同一視の最終判断は利用側」— llms.txt と同文。

## 4. 実装ノート

- 成果物の取得は CloudFront 経由の公開 URL (バケット直読みしない —
  キャッシュに乗せる)。Lambda コンテナ内に小さな LRU (pair→digest 等) を
  持ってよいが、正は常に S3 側 (stateless の範囲)。
- 大きい成果物 (events 数十 MB) は全量をメモリに広げず、フィルタ後
  limit 件で切って件数+URL を添える。routes.digest / mapping は
  gzip 数 MB 級なので全量ロードして切り出しで足りる。
- 認可: v1 は読み取り系すべて匿名 (成果物は既に公開)。run_compare も
  既存の匿名ジョブと同じコストガード (W3-2c) を通るため新設計は不要。
  ガードを超える需要が観測されたら API キー/OAuth を検討 (先送り)。
- 入力検証は既存の _safe_id / safe_uid を流用。

## 5. 想定ユースケース (検証シナリオを兼ねる)

1. 自治体・事業者担当者: 「うちの市のバス、4月の改正で何が変わる?」
   → find_feeds → find_generations → run_compare → get_digest → 要約
2. データ作成者: 「新旧を比べて直すべき行を教えて」→ get_residuals +
   get_events(TECHNICAL_ID_CHURN) → trip/stop の指摘
3. 研究者: 「県内全フィードの直近改正で減便を一覧に」→ find_feeds →
   ループで run_compare/get_digest (コストガードの挙動確認を兼ねる)
4. 経年結合: 「この stop_id は新データでどれ?」→ map_ids

## 6. 検証計画

- **contract test** (実装と同時): ツールを in-process で叩き、応答スキーマ・
  上限・省略の明示・不在ペアのエラー形を機械検査。SDK 更新の受け入れ条件。
- **RD4c-2: EXP2 エージェント版 A/B** (論文実験を兼ねる):
  12フィードの公式告知を渡し、(A) MCP 接続エージェント vs (B) URL+llms.txt
  のみ、で突合タスクを自律実行させる。測定: 判定一致率 (正解=EXP2 シート)・
  ツール/fetch 呼び出し回数・迷子率。**「MCP が何を上乗せしたか」を定量化**。
- コールドスタート課題: 「◯◯市のバスは最近どう変わった?」だけで
  探索→比較→要約の完走率 (ユースケース1の直接検証)。

## 7. 段階と DoD

- **RD4c-1a: サーバー骨格+読み取り系** — 最新仕様・SDK の確認 (DoD 必須)、
  Streamable HTTP、§3 の読み取りツール、contract test、/mcp デプロイ。
  DoD: Claude (デスクトップ or claude.ai) から接続し、既存ペアで
  ユースケース2・4 が対話で完了する。
- **RD4c-1b: run_compare** — ジョブ投入+ポーリング。DoD: コールドスタート
  課題 (ユースケース1) が新規ペアで完走。コストガードの発火を実測。
- **RD4c-2: A/B 検証** — §6。DoD: 判定一致率と呼び出し回数の比較を
  docs/verification/ に記録。
- 先送り: 認可強化、ローカル MCP (CLI 同梱で compare をローカル実行する
  stdio サーバー — 研究者のバッチ用途に将来価値があるが、まず remote を出す)。

## 8. 棄却・保留

- サーバー側での自然言語要約 (棄却): 設計原則4 (コアに LLM を入れない) は
  MCP 層にも適用。事実の返却に徹し、文章化はクライアント側の LLM。
- resources (MCP の静的リソース面) の多用 (保留): digest は URL で既に
  取得可能。ツール応答に URL を含める方が、resources 対応が薄い
  クライアントでも壊れない。
- WebSocket/SSE 前提の push (棄却): ジョブは秒〜分で終わる。ポーリングで足りる。
