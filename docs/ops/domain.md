# 独自ドメイン diff.gtfs.jp (2026-07-11 開通)

方式A (docs 議論 2026-07-11): gtfs.jp はレジストラ=お名前.com、DNS=さくら
インターネット (ns1/ns2.dns.ne.jp)。さくらのゾーン編集に CNAME 2本を追加した。

| エントリ | タイプ | 値 | 用途 |
|---|---|---|---|
| `_2b93f10421b5720e4d9e244737375915.diff` | CNAME | `_8e5a…jkddzztszm.acm-validations.aws.` | ACM 検証。**証明書自動更新のため恒久設置 (削除禁止)** |
| `diff` | CNAME | `d22mbbm5uatfcc.cloudfront.net.` | 本体 |

- 証明書: ACM us-east-1 `arn:…:certificate/d4b34c14-…` (CloudFront 用は us-east-1
  限定)。ARN とドメインは infra/cdk.json の context (`site_domain` /
  `site_certificate_arn`) で永続化し、CDK が CloudFront 代替ドメインと
  Cognito コールバック (新旧両ドメイン許可) に反映する。
- 旧 URL (d22mbbm5uatfcc.cloudfront.net) も引き続き有効 (発行済み結果 URL を守る)。
- Google OAuth 側の変更は不要 (リダイレクトは Cognito ドメイン宛てのまま)。
- 開通確認 (2026-07-11): トップ/terms/API/既存レポート 200、TLS CN=diff.gtfs.jp、
  ログインは新ドメインでユーザーが動作確認。
