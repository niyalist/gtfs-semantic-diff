# AN2 検証記録: サーバ側アクセス計測 (2026-09-19)

方針・手順: docs/ops/analytics.md。roadmap AN2 の DoD (a) の記録。
(b) 初回の月次集計と (c) 運用開始は 2026-10 月初に追記する。

## デプロイと配信確認 (DoD a)

- 2026-09-19 (JST) 出張用 Mac から 2 回デプロイ:
  1. ログバケット `AccessLogs` + CloudFront Logging + MCP 利用記録 (CloudFront
     の更新を含み Total 837s)
  2. ログレベル修正 (下記) — イメージ更新のみ、Total 115s
- デプロイ後: サイト 200、`POST /api/uploads` 200、レポート入口 200。
- CloudFront 側: `Logging.Enabled=true, IncludeCookies=false, Prefix=cloudfront/`。
  ログバケットに配信アカウント (awslogsdelivery `c4c1ede6…`) の FULL_CONTROL
  ACL が自動付与されていることを確認。ライフサイクル `expire-raw-logs` 90 日 Enabled。
- ログの到着: 有効化から約 20 分で最初のファイル
  (`cloudfront/EYTCIY3LJP6UZ.2026-09-19-05.*.gz`) が到着。
- 集計スクリプトの本番実走: `access_stats.py --from 2026-09-19 --to 2026-09-19`
  → 5 リクエスト (スモークテストの curl 3、MCP 呼出 1、MCP サーバー自身の台帳読み 1)。
  実ログで見つけた分類漏れ 2 件をその場で追加:
  `/feeds/{org}__{feed}.json` → `feed_ledger`、UA `gtfs-semdiff-mcp` → `internal`
  (自サーバーの内部リクエストを外部利用と混ぜない)。

## MCP 利用記録の実証

このセッションの MCP コネクタ (claude.ai) から `get_digest` を 1 回呼び、
api Lambda の CloudWatch Logs に次の 1 行が出ることを確認:

```
mcp_request {"mcp": "tools/call", "ua": "Claude-User", "tool": "get_digest",
             "args": {"pair": "nagai-unyu__Nagaibus__4a4a81e7__b1be1add", "lang": "ja"}}
```

IP は含まれない。UA が `Claude-User` なので、CloudFront ログ側の
クライアント種別 (`ai_agent / Claude-User`) とも突き合わせられる。

## 副産物: Lambda の INFO ログが 14 日間 0 件だった潜在バグ

最初のデプロイ後、`mcp_request` (INFO) が CloudWatch に出なかった。worker / api
の両ロググループを 14 日遡っても INFO が 0 件 (WARNING は出る) で、原因は
handler.py の `logging.basicConfig(level=INFO)` — Lambda の Python ランタイムは
root logger に既にハンドラを付けているため basicConfig が無効になる。
`logging.getLogger().setLevel(INFO)` を追加し (mcp_entry は自身の logger にも
INFO を設定)、Lambda 相当の設定を模したコンテナ内テストで INFO が出ることを
確認してから再デプロイ。以後、worker の pipeline ログ (explained_ratio 等) も
CloudWatch に出る (ログ量は 1 ジョブあたり数十行で、コスト上の問題はない)。

## 初回の月次集計 (DoD b — 2026-10-06 実施、対象 2026-09-01〜30)

`access_stats.py --from 2026-09-01 --to 2026-09-30 -o data/stats/2026-09`
(ログ 671 ファイルを S3 から読み流し)。ログは AN2 有効化 (9/19) 以降の
12 日分。数値の正は data/stats/2026-09.{md,json} (gitignore)、ここには
研究・運営判断に使う要点のみ写す:

- **総リクエスト 5,228 / 配信 125.9MB / 12日間**。ブラウザ閲覧者 (visitors)
  は日あたり 4〜37 の概数
- **MCP 利用が実在し、増加傾向**: 日別 mcp 7→97 (9/30)。クライアント内訳は
  Claude-User 304・codex-mcp-client 260・ChatGPT-User 24・openai-mcp 4 —
  **複数系統の AI エージェントからの利用が現実に始まっている** (I6/RD4c の
  狙いどおり)。MCP 415 呼に対しブラウザ render 57 — 現時点で機械利用が
  人間の閲覧を上回る
- レポート別 render は匿名アップロード (23) が最多、公開ペアは福崎町・
  しおかぜライン等 21 ペアに分散。digest 直読みは 1 件 (nagai 基準ペア)
- 流入元: google 17・Teams 13・t.co 5 — SNS/チャット共有が検索と同程度
- ai_crawler (Bytespider 174・ClaudeBot 174) と脆弱性スキャン
  (/api/.env 等 — 全て 4xx) が相応にあり、403 が 2,259 件と多いのは
  これらとプリフライト拒否によるもの。実害なし
- KNOWN_AGENTS の追加は今回なし (codex-mcp-client / NoMoreVibe は "other" の
  まま観察継続 — 分類追加するほどの定常性はまだ不明)
- XL1 実測 (9/17 の `gtfs-semantic-diff-xl-measure` UA 302 件) が "other" に
  計上されている — 自分の計測は UA を付けておいたので分離可能 (今後も計測
  スクリプトには識別 UA を付けること)

## 月次運用の開始 (DoD c)

- 運用: docs/ops/analytics.md §4 のとおり「月初に前月分を集計し
  data/stats/YYYY-MM に保存、要点を本記録群に写す」。初回 = 本節。
  次回は 2026-11 月初 (10 月分)
- CLAUDE.md 残タスクの AN2 は「初回集計の記録待ち」→ 月次運用中に更新
