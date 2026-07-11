# W3-2b 検証記録: ログイン・履歴・zip 保存 (2026-07-11)

設計: docs/design/web.md「W3-2 詳細方針」。実装: infra/runtime/webusers.py (純ロジック) +
handler.py (/api/config, /api/me/*) + delivery.py (Cognito) + web/index.html (PKCE)。

## 構成

- Cognito UserPool `ap-northeast-1_JjjzGd33G` + Hosted UI
  `gtfs-semdiff.auth.ap-northeast-1.amazoncognito.com` + Google IdP
  (client secret は Secrets Manager `gtfs-semdiff/google-oauth` に**文字列そのまま**格納。
  client_id は infra/cdk.json の context で永続化)
- 認証は API Gateway の JWT オーソライザ (`/api/me` と `/api/me/{proxy+}` のみ)。
  匿名機能は無認証のまま。フロントは PKCE 付き認可コード (vanilla JS、
  トークンは localStorage、リフレッシュなし = 失効時は再ログイン)
- 内部 user_id = 正規化 email の SHA-256 先頭 (webusers.user_id_from_email)。
  UserData テーブル (pk=user_id, sk=`profile` / `run#{ISO}#{job}` / `zip#{id}`、RETAIN)
- ログインユーザーのアップロード: 結果は r/u/ (恒久・ランダム URL)、zip は
  userzips/ に複製し agency_name + feed_start_date から表示名を自動生成

## 検証 (ユーザーがブラウザで実操作、2026-07-11)

- ✓ Google ログイン → email 表示 / ログアウト
- ✓ リポジトリ比較の履歴記録・並べ替え・「開く」
- ✓ 同条件で再比較 (lazy 即返し) / 新側を最新にして再比較
- ✓ アップロード比較 → zip 自動保存 (名古屋市バス2件、自動表示名) → プルダウン再利用
- ✓ 履歴・保存 zip の削除 (アップロード履歴は結果 URL ごと、zip は S3 実体ごと)
- ✓ 匿名機能の回帰 (lazy 即返し・レポート閲覧)、/api/me 無認証 401

## 途中で直した不具合 (それぞれ単一コミット)

1. Dockerfile に webusers.py の COPY 漏れ → import 失敗で API 全体 500
2. API Lambda: Secrets Manager の値が JSON でなく生文字列 → SecretValue を全文字列読みに
3. `_resp` が DynamoDB の Decimal を JSON 化できず /api/me/zips が 500
   (**zip は保存されているのに一覧が空に見える**というユーザー報告の正体)
4. 日付表示が UTC (JST では翌日) → UI はブラウザ TZ、表示名焼き込みは JST に
5. 「最新世代と比較」の意味が不明確 → ボタン名変更 + 実行時に新旧を明示 + 注記

## 既知の制限

- トークンリフレッシュ未実装 (1時間で再ログイン。必要になったら refresh_token 対応)
- 履歴のイベント規模ソートは未実装 (roadmap の W3-2b 要件のうち唯一の残り。
  index.json にイベント数を載せる案 = 観測所構想と同時にやるのが自然)
- Google 同意画面はテストモードのままの可能性 (公開時に「本番環境」へ)
