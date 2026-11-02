# 利用状況の月次トレンド (diff.gtfs.jp)

AN2 (docs/ops/analytics.md) の月次集計の**要点をここに1行ずつ積む**。数値の正は
data/stats/YYYY-MM.{md,json} (ローカル・gitignore)、手順は analytics.md §4。
研究・発表に引用する数字はこの表と各月の特記からのみ取る。

## 指標の定義 (読み方の注意)

- **mcp(生)** = CloudFront ログの POST /mcp (2xx) — **initialize 等の
  ハンドシェイクを含む**。MCP クライアント (Codex 等) は登録済みサーバー全てに
  セッション開始時 initialize を打つため、この数は「登録されている度合い」の指標
- **mcp実呼** = CloudWatch の `mcp_request` のうち `tools/call` — こちらが
  「実際に分析に使われた回数」(analytics.md §3 のクエリ)
- visitors = ブラウザ閲覧者の日毎概数の月間ピーク値を記載 (詳細は月次 md)

## 月次トレンド

| 月 | requests | mcp(生) | **mcp実呼** | renders | visitors/日 (max) | 特記 |
|---|---:|---:|---:|---:|---:|---|
| 2026-09 (9/19〜) | 5,228 | 415 | **1** | 57 | 37 | ログ開始。実呼1は AN2 検証の自己呼出 |
| 2026-10 | 12,551 | 2,604 | **2** | 97 | 26 | 実呼2 = Codex 利用者1名の find_feeds ×2 (米 Duluth Transit を探索 → 国内のみで空振り)。mcp(生) の急増は Codex 系ハンドシェイク |

## 分かっていること (2026-11-02 時点の解釈)

- **MCP 経由の実分析はまだ起きていない**。45日間の tools/call は3件のみで、
  1件は自己検証、2件は Codex 利用者1名の探索 (米国フィードを期待 → 本サービスは
  gtfs-data.jp +アップロードのみで空振り)。9月集計の「機械利用がブラウザ閲覧を
  上回る」は POST /mcp をそのまま数えた**過大解釈だった** (訂正:
  AN2_access_stats.md 2026-11-02 追記)
- 一方で**「登録」は着実に広がっている**: codex-mcp-client のハンドシェイクが
  33日間・38 相異なり IP・多数のバージョン系列から定常的に来ており、設定に
  入れている環境は複数ある (クラウド実行の IP 揺れを含むため人数は不明)。
  発見導線 (llms.txt・developers) は機能している — 使われるかは今後の観察
- 国際ユーザーの期待と現機能のギャップ: Duluth の find_feeds 空振りは
  「国際フィードの探索対応 (Mobility Database 連携等)」への示唆 — XL4/将来項目
- ブラウザ利用は小規模安定 (visitors 3〜37/日、render 2〜97/月)。流入は
  google が最多 (10月 52)、GitHub・SNS 経由が少量
