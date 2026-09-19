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

## 残り (DoD b・c)

- 2026-10 月初: 9 月分 (9/19〜) を集計し、レポート別 render・流入元・
  クライアント種別の実データをここに追記。KNOWN_AGENTS の追加があればその記録。
- 月次運用の開始を CLAUDE.md / roadmap に反映。
