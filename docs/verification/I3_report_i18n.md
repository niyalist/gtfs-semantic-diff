# I3 検証: レポートの英語品質と JSON 言語中立化 (進行中、2026-09-15)

設計: docs/design/i18n.md I3 / presentation.md 改訂 (2026-09-15)。
実装: fcac44a ほか、版 2026.9.15.1。

## 焼き込みの全数監査 (完了)

永井 (2025-04→2025-10) の core bundle を CJK 走査 — 223 パス。分類:

- フィード由来データ (停留所名・路線名・trip_id・service_id・feed_version 等)
  と ja/en 対のカタログ → 正当 (翻訳しない)
- **当方が日本語を合成している生成ラベル = 6箇所**: ①「◯◯ 循環」(dg)
  ②「…（△△先回り）」(loop leg) ③「A・B経由」④「経路N」+重複連番 (分冊)
  ⑤ OGP 題名 (bundle._page_meta) ⑥ zip/履歴の表示名 (webusers)

## 対応 (label_parts 方式) と機械検証 (完了)

- ja ラベル文字列は不変のまま、構造化 parts を additive 併記。en は viewer の
  partsLabel が組み立て (ja では恒等 — vitest で固定 = ja 表示不変の構造保証)
- pytest 282 (parts 合成テスト: 循環 leg・分冊先回り)、vitest 27 (partsLabel
  6種 + ja 恒等 + parts なし恒等)。ビューア初期言語 = navigator.language
  (jsdom=en で既存テストが落ちたことが判定変更の裏検証になった — テストは
  ja 固定を明示)

## 本番検証 (完了)

永井ペアを 2026.9.15.1 で lazy 再生成し、配信 viewer_data を確認:

- label_parts 9件 (loop 3・first 1・via 5)、**ja ラベルは監査時と完全一致**
- meta.page_title_en = "永井運輸株式会社 — GTFS timetable change report
  (2025-04-01 → 2025-10-01)" (タブ題名の言語追従用。OGP head は ja のまま)
- presentation.self_check = []

## 残 (I3 完了まで)

- [ ] en モード DOM の CJK 監査ハーネス: 停留所名が英語の合成フィードで
      App を en レンダリングし CJK ゼロを vitest 常設 (データが英語なら
      CJK 検出 = 当方の焼き込み、という原理)
- [ ] I1 国際フィード2件以上の実レポートを英語 UI で通読 (チェックリスト)
- [ ] 検証フィード (ja) の目視 — 表示不変の最終確認 (ユーザー)
