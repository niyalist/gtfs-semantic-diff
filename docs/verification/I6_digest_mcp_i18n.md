# I6 検証: digest 英語版の併設と MCP の en 化 (完了 2026-09-16)

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

## 英語実走 (完了 2026-09-16)

- [x] **Claude Desktop から利用可能を確認** (ユーザー実施)。ChatGPT は
      通常チャットでは不可・**Work でのみ利用可能** (ユーザー環境の
      組織ポリシー由来とみられる — 2026-08 の同様の観察と一致)。
      いずれにせよ AI クライアントからの英語利用を確認
- 補助記録: 実プロトコル (2026-07-28 世代 tools/call) での
  get_digest(pair, lang="en") 直叩きも成功 — "# Change digest: 永井運輸…"
- 観察: コネクタ未有効の ChatGPT チャットは Web 検索に流れ、llms.txt 経由で
  URL 規則には正しく到達した (発見導線は機能) がツール実行に至らず —
  クライアント側でのコネクタ有効化が前提
