# 開発環境セットアップ (別マシンでの作業手順)

2026-09-17 作成 (出張用に整備)。新しい Mac で clone → テスト → デプロイまで。

## 0. コード取得 — git を正とする (iCloud 同期に依存しない)

```sh
git clone git@github.com:niyalist/gtfs-semantic-diff.git
cd gtfs-semantic-diff
```

- origin は **SSH** (git@github.com)。新マシンに SSH 鍵が無ければ
  `gh auth login` (HTTPS) でも可: `gh repo clone niyalist/gtfs-semantic-diff`
- **iCloud 同期下のパス (~/Documents 等) に置く場合の注意**: venv は必ず
  `.venv.nosync` (下記)。既存 Mac と同じ iCloud パスを共有する場合でも、
  コードの授受は git push/pull で行う (iCloud の同期遅延・.git 破損リスクを
  踏まないため。詳細は README の iCloud 注記)
- clone 先を iCloud 外 (例: `~/dev/`) にすれば .nosync の悩み自体が消える

## 1. Python (コア + CDK)

Python 3.14 と uv が前提 (`brew install uv` → uv が Python も入れる):

```sh
uv venv .venv.nosync --python 3.14
ln -s .venv.nosync .venv
uv pip install -e '.[dev]' --python .venv.nosync/bin/python
uv pip install -r infra/requirements.txt --python .venv.nosync/bin/python  # CDK 用
.venv.nosync/bin/python -m pytest -q    # 294 passed を確認
```

infra/cdk.json の app は `../.venv.nosync/bin/python app.py` を指すため、
**CDK の依存も同じ venv に入れる** (2行目の requirements.txt)。

## 2. Node (viewer + cdk CLI)

Node 22/24 系 (`brew install node`)。

```sh
cd viewer && npm install && npm test && cd ..   # vitest 36 件
# ビューア変更時のテンプレート再生成:
scripts/build_viewer.sh
```

cdk CLI は `npx cdk` で都度取得されるので個別インストール不要。

## 3. AWS (デプロイ)

1. AWS CLI v2: `brew install awscli`
2. `~/.aws/config` に以下を追記 (SSO なので秘密情報なし):

```ini
[profile AdministratorAccess-948645358251]
sso_session = gtfs-semdiff
sso_account_id = 948645358251
sso_role_name = AdministratorAccess
region = ap-northeast-1
output = json

[sso-session gtfs-semdiff]
sso_start_url = https://d-956794b92a.awsapps.com/start
sso_region = ap-northeast-1
sso_registration_scopes = sso:account:access
```

3. `aws sso login --profile AdministratorAccess-948645358251` (ブラウザで承認)
4. **Docker Desktop** を入れて起動しておく (worker は Docker イメージビルド必須。
   Apple Silicon 前提 — Intel Mac では arm64 のクロスビルドになり非常に遅い)
5. デプロイ:

```sh
cd infra && AWS_PROFILE=AdministratorAccess-948645358251 npx cdk deploy --require-approval never
```

デプロイ直後は `curl -s -o /dev/null -w "%{http_code}" -X POST
https://diff.gtfs.jp/api/uploads` が 200 を返すことを確認する習慣
(2026-09-17 の preflight.py コピー漏れ事故の教訓)。

## 4. データ (git 管理外) — 必要になったときだけ

`data/` は gitignore。用途別に:

- **API 系検証フィード** (永井・地鉄・朝日町): `gtfs-semantic-diff fetch --org … --feed …`
  で都度取得 (キャッシュされる)
- **国際検証フィード** (trimet/rome/mbta/stm/prt/swiss/ovapi_nl):
  `scripts/fetch_intl_feeds.py` が恒久固定 URL から再取得 (I1 台帳)。
  XL3 再実測に必要なのはこれ
- **ローカル zip 系** (臨港・名古屋): 元 Mac の `data/` からコピーするしかない。
  出張中に必要になる見込みは低い

## 5. Claude Code

- リポジトリの CLAUDE.md が恒常ルールの正 (プロジェクトメモリはマシン別 —
  重要事項は CLAUDE.md に昇格済みなので新マシンでも困らない)
- `gh` CLI を使うなら `gh auth login`

## 6. 作業開始前チェックリスト

1. `git pull` — 最新か
2. `.venv.nosync/bin/python -m pytest -q` — 緑か
3. デプロイするなら: `aws sso login` 済みか、Docker 起動済みか
4. 終わったら `git push` (別マシン間の受け渡しは常に git 経由)
