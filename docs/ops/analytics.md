# アクセス計測 (diff.gtfs.jp) — サーバ側ログ中心

2026-09-19 決定 (AN2)。ページの閲覧・API・MCP の利用状況を把握する手段として、
**クライアント側の計測タグ (Google アナリティクス等) は当面置かず、CloudFront の
標準ログと Lambda の構造化ログをサーバ側で集計する**。検索流入・インデックスは
Search Console (AN1、docs/ops/search_console.md) の担当。

## 1. 判断の記録: なぜ GA を入れなかったか

2026-09-19 に GA4 の導入を実装まで進めたうえで見送った (コードは revert 済み、
この節がその記録)。

- **知りたいことの本命が GA では測れない**: 本サービスは API / MCP / AI
  エージェント経由の利用を重視しているが、GA はブラウザで描画された閲覧しか
  測れない。それらはサーバ側の記録でしか分からず、二重の計測系を持つ理由が薄い。
- **コミュニティの受け止め**: Web サイトへの GA 設置自体は広く許容されているが、
  プライバシー志向の開発者や EU の公的機関・研究者には慎重な人が多い。国際
  フィード (swiss / NL 等) を扱い Summit で国際的に見せる時期に、「Cookie 同意も
  なく Google に送っているのか」と説明を求められる可能性を負う価値がない。
  (なお最も強く嫌われるのは CLI / ライブラリ本体へのテレメトリで、これは
  どの案でも入れない。)
- **検討した折衷案**: (a) 静的ページのみ GA・レポートには入れない —
  「自分で使いに来た人だけ測る」線引きは説明可能だが、本命のレポート閲覧が
  測れない。(b) Cookie なし解析 (Plausible 等) — 姿勢の信号にはなるが、ベンダー
  とコストが増える。(c) **サーバ側ログ** — Google に何も送らず Cookie も置かず、
  規約 §3 の既存の記述 (結果ページの生成・閲覧の状況を記録、IP は最長 90 日) の
  範囲内。API/MCP も同じ土俵で数えられる。→ (c) を採用。
- 再検討の条件: リアルタイムの流入確認や UX 分析 (スクロール・操作) が必要に
  なったとき。そのときも候補は (a) か (b) で、CLI には入れない。

## 2. 何をどこで記録しているか

| 知りたいこと | 記録の所在 | 保持 |
|---|---|---|
| ページ閲覧 (どのレポートが・どこから・どんなクライアントで) | CloudFront 標準ログ (S3 `AccessLogs` バケット、`cloudfront/` 接頭辞、Cookie なし) | **90 日で自動削除** (IP を含むため。規約 §3) |
| レポートが実際に描画された回数 | 同上 — ビューアのデータ JSON (`r/{pair}/v/{版}.json`) の取得数 = render | 同上 |
| API 呼出 | 同上 (`/api/*`)。ジョブの投入・完了・所要時間は Jobs テーブル (30 日 TTL) | 同上 |
| MCP 利用 (どのツールが・どのペアに・どのクライアントから) | api Lambda の CloudWatch Logs に 1 行 JSON (`mcp_request {...}`、infra/runtime/mcp_entry.py `request_log_fields`) — IP を含まない。CloudFront ログには `POST /mcp` としか残らないため | 無期限 (IP なし) |
| どのペアが生成されたか | S3 `r/{pair}/index.json` (版台帳) | 恒久 |
| 集計結果 (匿名・集計済み) | `scripts/access_stats.py` の出力 (Markdown + JSON)。IP・ハッシュを含まない | 恒久 (data/stats/ は gitignore。研究に使う分は docs/verification/ に写す) |

生ログは 90 日で消えるので、**月に一度は集計を回して結果を残す** (§4)。

自サーバーの内部リクエスト (MCP サーバーが CloudFront 経由で台帳・成果物を
読む。UA `gtfs-semdiff-mcp`) は CloudFront ログにも載るが、集計では
`internal` として外部利用と分けて数える。

注: Lambda の Python ランタイムでは `logging.basicConfig` が効かず INFO が
落ちる (2026-09-19 に判明・修正: handler.py で root logger のレベルを直接設定)。
新しい利用記録を INFO で出すときはこの前提を思い出すこと。

## 3. 集計スクリプト

```sh
uv pip install -e '.[ops]' --python .venv.nosync/bin/python   # boto3 (初回のみ)
AWS_PROFILE=AdministratorAccess-948645358251 \
  .venv.nosync/bin/python scripts/access_stats.py --from 2026-09-01 --to 2026-09-30 \
  -o data/stats/2026-09        # → data/stats/2026-09.md / .json
```

- S3 から読み流し、**生ログをローカルに残さない**。バケット名は
  スタック出力 `AccessLogBucket` から自動で引く (`--bucket` で上書き可)。
- ローカルのログ (gz 可) を集計するには `--files a.gz b.gz -o …`。
- 出力の見方:
  - **日別**: requests / renders (レポート描画) / visitors (ブラウザでトップ・
    レポートを見た人の概数 — IP+UA の実行ごとの乱数ソルト付きハッシュで数え、
    ハッシュは捨てる) / api / mcp
  - **ページ種別**: 全クライアント vs ブラウザのみ。差が「機械の利用」
  - **レポート別**: pair ごとの render / entry / version / digest / events / mapping
  - **流入元**: ブラウザ閲覧の Referer ホスト (自サイト除く)
  - **クライアント種別**: browser / ai_agent (ChatGPT-User, Claude-User …) /
    ai_crawler (GPTBot, ClaudeBot …) / crawler / preview (SNS のカード生成) /
    program (curl, python-httpx …) / bot / other。判定表は `KNOWN_AGENTS`
  - **エッジ**: IATA 3 文字 (NRT/HND/KIX = 日本、FRA/AMS = 欧州 …)。地域の目安
- 分類の追加 (新しい AI エージェントの UA 等) は `KNOWN_AGENTS` に足し、
  tests/test_access_stats.py に例を追加する。

MCP のツール別集計は CloudWatch Logs Insights で (ロググループは api Lambda):

```
fields @timestamp, @message
| filter @message like /mcp_request/
| parse @message '"tool": "*"' as tool
| stats count() by tool
```

## 4. 運用

- **月初**: 前月分を `access_stats.py` で集計し `data/stats/YYYY-MM.{md,json}` に
  保存 (90 日で生ログが消えるため、3 か月以上空けない)。
- 研究・発表に使う数字は、集計済みの出力からのみ引用する (規約 §3:
  匿名化・集計した形でのみ研究利用)。
- 規約 §3 の範囲を超える計測 (個人の識別、ログイン ID との突合、CLI への
  テレメトリ) はしない。
- 既存の admin ページ (docs/design/admin.md) は「運営に必要な範囲の閲覧」用で、
  こちらは「集計」用 — 役割を混ぜない。

## 5. 将来の選択肢 (必要になったら)

- 日次の自動集計 (EventBridge + Lambda で前日分を IP なしの集計に落とす):
  手動集計を忘れて生ログが消えるリスクを構造的に消せる。現状は規模に対して
  過剰と判断 (admin.md の BI 不採用と同じ理由)。
- CloudFront 標準ログ v2 (出力フィールド選択・Parquet) に切り替えれば IP を
  最初から落とせ、生ログを長期保持できる。CDK での定義が L1 になるため保留。

## 関連

- docs/ops/search_console.md — AN1 (検索流入・インデックス)
- docs/design/admin.md — 運営管理と規約 §3 の整合 (2026-07-12)
- web/terms.html §3 — 利用状況の記録 (IP は最長 90 日、研究は匿名・集計のみ)
- infra/stacks/delivery.py (`AccessLogs`)、infra/runtime/mcp_entry.py、
  scripts/access_stats.py、tests/test_access_stats.py
