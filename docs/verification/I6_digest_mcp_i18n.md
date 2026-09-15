# I6 検証: digest 英語版の併設と MCP の en 化 (2026-09-15)

設計: docs/design/i18n.md I6 (+実装時判断: digest.en.json は作らず JSON を
言語中立に)。実装: 2026.9.15.5。

## 機械検証 (完了)

- pytest 286 全通過。新規: en 見出し契約 (1. Comparison overview 〜
  7. Verification (explanation ledger))・explained_ratio の ja/en 数値一致・
  ja レンダ不変 (lang 省略 = lang="ja")・MCP get_digest の en→ja
  フォールバック (英語注記付き)
- ja バイト不変: 本番 baseline (2026.9.15.3 生成の永井 digest.md) と
  新コードの ja 出力を突合 — 本文完全一致 (差は環境依存の深掘り URL 節のみ)

## 本番 E2E (完了、永井 2026.9.15.5 再生成)

- r/{pair}.digest.en.md 配信: "# Change digest: 永井運輸株式会社"
- 数値一致: explained_ratio 1.0000 (14399/14399) が ja/en で同一。
  便数行も en 語彙 (Weekday 208→202 trips, ...) で同数
- HTML head: rel=alternate hreflang="en" → .digest.en.md (発見導線)
- index.json artifacts: digest_en_md {url, schema: 1, lang: "en"}
- 旧ペア (2026.9.15.3 の上士幌) の .digest.en.md は未生成 (期待どおり) —
  MCP get_digest は ja へフォールバックし英語注記を前置する (contract test)

## 残 (DoD)

- [ ] ChatGPT / Claude コネクタからの英語実走記録 (ユーザー実施。
      ツール説明が en になったことと get_digest(lang) の動作確認を兼ねる)
