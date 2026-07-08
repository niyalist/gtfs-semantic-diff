# W3-0 運用手順: 結果配信基盤 (S3 + CloudFront)

対象: roadmap W3-0。IaC は infra/ (AWS CDK, Python)。リージョン ap-northeast-1。
独自ドメインは後付け (それまで CloudFront 既定ドメインを使う)。

## 前提 (アカウント初期設定 — 新規アカウントで1回だけ)

1. **ルートユーザーの保護**: ルートで MFA を有効化。ルートのアクセスキーは作らない。
   以後ルートは請求・アカウント設定のみに使用
2. **請求ガード**: Billing → Budgets で月額アラートを1本 (CDK でも作るが空白期間を
   無くすため)。Cost Explorer を有効化 (初回クリック)
3. **作業用 ID (IAM Identity Center)**: 有効化 (ホームリージョン: 東京) →
   ユーザー作成 (自分) → MFA 設定 → 許可セット AdministratorAccess を作成し
   アカウント×ユーザーへ割り当て → アクセスポータル URL を控える
4. **ローカル**: `brew install awscli node` → `aws configure sso`
   (SSO start URL = アクセスポータル URL、region = ap-northeast-1、
   プロファイル名 = `gtfs-semantic-diff`) →
   `aws sts get-caller-identity --profile gtfs-semantic-diff` で確認

## デプロイ

```sh
# 依存 (初回)
.venv.nosync/bin/pip install -r infra/requirements.txt

cd infra
# ブートストラップ (アカウント×リージョンで初回のみ)
AWS_PROFILE=gtfs-semantic-diff npx aws-cdk bootstrap

# デプロイ (alert_email は Budgets の通知先)
AWS_PROFILE=gtfs-semantic-diff npx aws-cdk deploy \
  -c alert_email=<メールアドレス> --outputs-file outputs.json
```

- `npx aws-cdk` は Node.js 経由で CDK CLI を都度実行する (グローバルインストール不要)
- outputs.json (バケット名・Distribution ID・ドメイン) は gitignore 済み。
  scripts/publish.py がこれを読む
- SSO セッションが切れたら `aws sso login --profile gtfs-semantic-diff`

## レポートの公開 (管理者用。W3-1 のジョブ API ができるまでの手段)

```sh
.venv.nosync/bin/gtfs-semantic-diff compare --org nagai-unyu --feed Nagaibus --html data/v3_nagai.html
.venv.nosync/bin/python scripts/publish.py data/v3_nagai.html \
  --id nagai-unyu__Nagaibus__prev_2__prev_1 --profile gtfs-semantic-diff
# → 公開 URL: https://dxxxx.cloudfront.net/r/nagai-unyu__Nagaibus__prev_2__prev_1.html
```

ID 規約: `org__feed__旧rid__新rid` (ローカル zip 入力は内容ハッシュか説明的な名前)。
上書き再公開は同じ ID で publish し直す (CloudFront は自動で無効化される)。

## 削除・撤収

- 個別レポート: `aws s3 rm s3://<bucket>/r/<id>.html --profile gtfs-semantic-diff`
- 全撤収: `npx aws-cdk destroy`。ただし結果バケットは RETAIN (公開済み URL を
  守るため) — 完全に消す場合はバケットを空にしてから手動削除

## コスト

想定: S3+CloudFront で月数十〜数百円 (低トラフィック)。Budgets 実績アラート
月 $20 の 50% / 100% でメール。月次の実績は本書に追記していく (W3-2 DoD)。

## 現行環境

環境固有の値 (アカウント ID・プロファイル名・配信ドメイン・バケット名) は
**docs/ops/local_env.md** (gitignore 対象) に記録する。2026-07-07 に
ap-northeast-1 へデプロイ済み。
- 教訓1: プロファイルに region が無く bootstrap が us-east-1 へ向かった →
  プロファイルに region 追記 + app.py で東京固定。us-east-1 の CDKToolkit は
  残置 (将来の ACM 証明書で使う)
- 教訓2: Apple Silicon のローカル Docker ビルドは arm64 — Lambda 側も
  Architecture.ARM_64 を明示しないと Runtime.InvalidEntrypoint

## DoD 確認 (W3-0) — 2026-07-07 達成

- [x] 検証フィードのレポートを publish し、公開 URL を取得 (永井・地鉄)
- [x] 第三者環境 (PC + 別回線のスマホ) で閲覧できる (ユーザー確認)
- [x] 地図タイル (地理院)・グリフがオンラインで表示される

## W3-1: ジョブ API と入力 UI (2026-07-07 デプロイ・技術検証済み)

- 入口: `https://<distribution-domain>/` (入力 UI)。
  API は同一ドメインの `/api/*` (CloudFront → HTTP API → Lambda)
- エンドポイント: `GET /api/gtfs/feeds?pref=N|org_id=` /
  `GET /api/gtfs/files?org=&feed=` (gtfs-data.jp プロキシ) /
  `POST /api/uploads` (presigned POST ×2, 上限100MB) /
  `POST /api/jobs` / `GET /api/jobs/{id}`
- ジョブ: api Lambda が DynamoDB (TTL 30日) に登録 → worker Lambda
  (コンテナ, ARM64, 2GB/15分/tmp2GB) を非同期起動 → compare → HTML を
  S3 r/ (gtfs-data.jp 入力) または r/anon/ (アップロード、30日で自動削除) へ
- 検証: 永井 (数秒)・臨港 zip アップロード (204→成功)・八戸 (11秒) を
  API 経由 end-to-end で確認
- ログ: CloudWatch `/aws/lambda/GtfsSemdiffDelivery-Api*` / `-Worker*`
- 教訓: Apple Silicon のローカル Docker ビルドは arm64 —
  Lambda 関数側も Architecture.ARM_64 を明示しないと Runtime.InvalidEntrypoint
- スロットリング: API 全体 rate 10/s, burst 20 (本格ガードは W3-2)
