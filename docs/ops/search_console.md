# Google Search Console (diff.gtfs.jp)

2026-09-17 起案 (AN1)。検索流入 (クエリ・表示回数・クリック) とインデックス状況を
把握するため、diff.gtfs.jp を Search Console に登録する。

## 方針: www.gtfs.jp とは独立したプロパティにする

- Search Console のデータはプロパティ単位。`https://www.gtfs.jp/` が
  **URL プレフィックスプロパティ**として登録されている場合、サブドメイン
  diff.gtfs.jp のデータは**一切含まれない** — 独立登録が必須。
- もし `gtfs.jp` が**ドメインプロパティ** (DNS 検証) なら diff のデータも
  混在収集されているが、別サービスとして独立に見たいので、いずれにせよ
  diff.gtfs.jp 専用プロパティを併設する (併設は自由。データは重複して両方に出る)。
  ※ どちらで登録済みかはプロパティ一覧の表記で判別できる:
  「gtfs.jp」(ドメイン) か「https://www.gtfs.jp/」(URL プレフィックス) か。

## プロパティ種別: URL プレフィックス `https://diff.gtfs.jp/` を採用

- **ドメインプロパティ (diff.gtfs.jp) は不採用**: DNS 検証で `diff.gtfs.jp` 名に
  TXT レコードが必要だが、`diff` は CloudFront への **CNAME** であり
  (docs/ops/domain.md)、同名に TXT を併置できない (DNS の CNAME 排他制約)。
  Google の代替 CNAME 検証 (ランダムラベル.diff.gtfs.jp) は技術的には可能だが、
  本サイトは https 一本・単一ホストなので URL プレフィックスで失うものがない。
- URL プレフィックスの検証は **HTML タグ方式** (meta タグ) を採用:
  検証物が repo (web/index.html) と CDK デプロイの管理下に入り、
  S3/CloudFront 再構築でも消えない。

## 登録手順

1. **[ユーザー]** https://search.google.com/search-console を www.gtfs.jp と
   同じ Google アカウントで開く → 左上のプロパティ選択 → 「プロパティを追加」
   → **URL プレフィックス** → `https://diff.gtfs.jp/` を入力。
2. **[ユーザー]** 所有権の確認方法で「**HTML タグ**」を選び、表示される
   `<meta name="google-site-verification" content="XXXX...">` の
   **content の値**を控える (この画面は閉じても後で再開できる)。
3. **[開発]** web/index.html の `<head>` にその meta タグを恒久設置し、
   `cd infra && AWS_PROFILE=AdministratorAccess-948645358251 npx cdk deploy` で反映。
   `curl -s https://diff.gtfs.jp/ | grep google-site-verification` で配信確認。
4. **[ユーザー]** Search Console に戻り「確認」を押す → 完了。
5. 検索パフォーマンスのデータが出るまで**数日**かかる (確認以前の分も
   遡って数週間分は出ることが多い)。

**meta タグは削除禁止**: Google は所有権を定期的に再確認するため、
外すとプロパティごと失効する。web/index.html にコメントで明記する。

## sitemap の扱い (AN1 で結論を記録する)

- レポートページ (`r/*.html`) は利用者生成で数が多く、トップからの恒常的な
  リンク導線も限定的。sitemap に載せる積極的理由は薄い
  (robots.txt は Allow のままにし、発見されたものは拒まない)。
- 静的ページ (`/`, `terms.html`, `developers.html`, `/docs/`) のみの小さな
  sitemap.xml は任意。登録後のカバレッジレポートを見てから要否を判断し、
  結論を docs/verification/AN1_search_console.md に記録する。

## 関連

- robots.txt / llms.txt — クロール・AI 向け導線 (全許可、i18n.md §4)
- docs/ops/domain.md — DNS 構成 (さくら、diff は CNAME)
