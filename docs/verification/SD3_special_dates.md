# SD3 検証ログ: 特定日の具体日付表示 + 同梱世代ノート (2026-07-23)

設計: docs/design/service_days.md §3。実装:
- bundle (`_special_day_services`): 表示の基礎を「calendar_dates の追加日」から
  **実効運行日集合** (SD1 と同じ定義、`load/day_types.effective_date_list` を
  共用) へ。`date_list` (上限 `[report] special_dates_list_max` = 30、超過は
  `truncated`) を追加。feed_overview に `comparison_scope` (SD2) も同梱
- viewer (FeedOverview): 「特定日」の行を「運行日: 2/14〜2/15、2/21〜2/23
  (計11日)」形式に (連続日をランに畳む `formatDateRuns`、8ラン超は「ほか N」)。
  第1部先頭に**同梱世代と比較範囲**の注記ブロック (▮ 記号第1チャネル)。
  i18n ja/en 対で追加 (fo_special_rundates / fo_scope_*)
- GENERATION_SCOPE を第1部イベント (_PART1_EVENT_TYPES) に追加

## 検証 (実行結果の確認)

| データ | 確認内容 |
|---|---|
| 合成 (tests/test_bundle.py) | 年末年始型 (追加日ベース) の date_list、PRT 型 (フラグ+大量削除) の date_list=["20260704"]、単一世代比較で comparison_scope=None |
| 佐賀 1月→4月 (HTML 埋め込み値) | ひなまつり周遊バス: 11日 (2/14, 2/15, 2/21〜2/23…)、年末・年始: 12/30〜1/3、火のみ運行: 8日、329日型 (曜日多数決不成立の毎日運行) は 30日で truncated。scope ノート (比較窓・primary・除外) も同居 |
| 桑名 改正前→同居 (HTML) | comparison_scope: 窓 6/1〜10/3、primary 7/11〜10/3、**「6/1〜7/10 は内容同一」**、新側除外 3 service/1,443便 の注記 |
| 伊勢鉄道 current ペア | 「運転日注意(みえ)」は密度が高く dow 型のまま (特定日に落ちない) — specials は空で正しい。scope も null (退化) |
| 回帰 | 全223テスト通過。既存キーの表示は不変 (date_list の無い旧バンドルは従来表示へフォールバック) |

備考: 特定日の日付は M/D 表示 (年跨ぎの年末年始も期間表示 first/last で補完)。
ブラウザ目視は sd3_saga.html / sd3_kuwana.html (スクラッチパッド) で実施。
