# 便対応付け (M8) の LCS メモ化 — P1 (2026-07-13)

## 背景

I1 (国際検証データセット) で、都市規模の国際フィード (TriMet 34MB 等) の比較が
30分級になることが判明。ステージ計測で **処理時間の 95% が便対応付け
(tripdelta) の停車列 LCS** と特定 (TriMet: 全体 1789s 中 1700s)。

## 鍵になった観測: 「便は多いが、パターンは少ない」

| フィード | 最大ブロック (路線×運行日) の便数 | その停車パターン種類 |
|---|---|---|
| TriMet | 384便 | 2 |
| MBTA Red Line | 547便 | 4 |
| ローマ 8BUS | 824便 | 4 |

ブロック内の便ペア総当たり (547² ≈ 30万回) の LCS は、実際には高々数種類の
パターン組の同じ計算の繰り返し。**(パターンA, パターンB) をキーに1回だけ計算**
するメモ化で潰した (events/tripdelta.py cached_lcs)。出力は完全同一
(純粋関数のキャッシュ。同一性テスト: test_lcs_memoization_identical_results)。

## 実測 (I1 データセット)

| feed | tripdelta 旧 | tripdelta 新 | 全体 |
|---|---|---|---|
| trimet | 1700s | **185s** (9.2x) | 1789s → 273s |
| mbta | 1356s | **294s** (4.6x) | >1800s (TO) → 1677s |

日本フィード回帰: 永井ペアでイベント JSON ハッシュ一致・pytest 204件。

## あわせて直した決定性の破れ (同じ調査で発見)

同一入力でも実行ごとにイベント JSON が変わる非決定性を発見 (PYTHONHASHSEED
依存の set 反復順が出力に漏れていた)。2箇所を sorted 化:

1. tripdelta 段1 exact_pairs の列挙順 (署名 set 交差)
2. TRAVEL_TIME 系 quantification の segments (set 交差 + 同差分値のタイブレーク
   なしで top_n 選抜まで揺れていた)

修正後、PYTHONHASHSEED=0〜99 で全ハッシュ一致を確認。回帰テスト2件。

## 次 (P2、docs/verification/intl_feeds.md IN-1〜3)

- ルール段 (L2) が新たな支配項 (MBTA 1291s)。RawDiff 1000万件超で非線形の疑い
- 便対応の残コスト (Δt×候補対)、RawDiff 由来のメモリ (RSS 10GB 級)
