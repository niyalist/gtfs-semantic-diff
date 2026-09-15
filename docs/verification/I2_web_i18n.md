# I2 検証: Web 静的ページの二言語化と error_en (2026-09-15)

実装: eda04b2、デプロイ: 2026-09-15 (156s)。設計: docs/design/i18n.md I2。

## 機械検証 (完了)

- pytest 282件全通過。新設 tests/test_web_i18n.py (6件):
  - en 領域 (index 辞書 / terms / developers の en ブロック) の CJK 文字ゼロ
  - index.html の ja/en 辞書キー完全一致 (ずれゼロ)
  - 3ページの言語トグル+localStorage "lang" 共有の存在
  - GtfsLoadError.en (パーサエラーの英語文、省略時 ja 代用)
- 3ページの inline JS を構文チェック (node new Function)
- 本番配信確認: index/terms/developers に二言語マーカーが配信されている

## 本番 E2E (完了)

壊れた入力の実ペア (立山町 prev_9→prev_5、translations.txt の引用符なしカンマ)
を再投入し、status API が三点セットを返すことを確認:

- error (ja): 「旧世代 (2024-04-25〜): translations.txt の 3行目: 列数がヘッダ
  (7列) と一致しません…」
- error_en: "older version (from 2024-04-25): translations.txt line 3: the
  number of columns (8) does not match the header (7). Likely an unquoted
  comma…"
- error_kind: "input"

MCP get_job_status は status API の透過なので同時に検証済み。

## 残 (ユーザー実操作)

- [ ] 英語設定ブラウザで「トップ→アップロード比較→レポート閲覧→ログイン→
      マイページ→削除」を英語で完結 (DoD の実操作確認。ログインは運用者のみ
      実施可能)。確認後に roadmap の I2 を完了へ
