# I4 検証: 国際フィードの技術対応 (完了 2026-09-16)

設計: docs/design/i18n.md I4。

## 地図基図 (G5) — 実装済み 2026.9.16.1

- viewer/src/lib/basemap.js: 地理院 pale / OSM 標準ラスタの2種。既定は座標の
  日本域判定 (緯度20〜46・経度122〜154)、利用者は地図右上ボタンで切替
  (localStorage "basemap" 共有)。切替はレイヤ/ソース差し替えのみ (setStyle
  不使用) でオーバーレイ不変。出典表記はソース追従
- OSM ラスタは繋ぎ (tile.openstreetmap.org の利用ポリシーに配慮した軽負荷。
  終着は RD3/PMTiles 自前配信)
- vitest 3件 (日本域判定・保存選択の優先・両言語ラベル/出典)。実物確認:
  data/intl/trimet_en_review.html (再生成済み — ポートランドで OSM が既定)

## 停留所名正規化の1字指標 (G6) — 実装済み

**規則**: 裸の1字指標 (A〜F・1〜9・丸数字・全角数字) は、剥がした残りが
ASCII 英数字で終わる場合は適用しない (単語指標「のりば」等は不変)。
剥がし損ねは「別クラスタのまま」に退化 — 誤結合しない (過剰適応しない原則)。

**データ根拠**:
- 国際3フィードの実測: 末尾1字剥がしが「正しく乗り場を束ねる」のは
  trimet 0/5・stm 0/8・rome 19/119 のみ。残りは "West A" (街路名)・
  "Milepost 8"・"-Zone B"・"VARCO 5" 等の実名破壊
- 国内479フィード・58,295停留所名の全数スキャン: 挙動差 **14件のみ、
  全てが旧規則の実名破壊の修正** (「津名一宮IC→津名一宮I」
  「アイセル21→アイセル」「KADODE OOIGAWA→KADODE OOIGAW」
  「フローラ・SAGAE→フローラ・SAG」等)。乗り場を剥がし損ねる例はゼロ
- 検証5フィード (永井・地鉄・臨港・名古屋・朝日町): 挙動差ゼロ = 出力不変
- 決定性の確認過程で「プロセス間でイベント JSON が揺れる」ように見えたが、
  実体は meta.generated_at (秒粒度) のみ — 決定性は保たれている

pytest 287 (正規化の ja/en 境界テスト追加)。detection.md 段階1に同期済み。

## I1 全ペアの動作記録 (2026-09-16、版 2026.9.16.2 のコア)

| feed | 所要 | explained_ratio | self_check | pages | 備考 |
|---|--:|--:|---|--:|---|
| trimet | 141s | 0.9999 | [] | — | 基図 OSM 自動選択を実物確認 |
| rome | 447s | 0.9834 | [] | — | frequencies 主体 |
| stm | 399s | 1.0000 (4桁丸め) | 既知の group46 2件のみ (SC トラック) | 232 | 残差 routes 218・stops 355 |
| mbta | 422s | 0.9527 | [] | 212 | 残差の主因は stop_times 486k・MBTA 拡張群 |
| prt | 65s | 1.0000 | [] | 100 | |
| ovapi_nl | 4977s | 0.9965 | [] | 1229 | 国家規模。transfers 残差 13.6万 |

(swiss はローカル未保持のため対象外 — I1 台帳の取得手順で再現可能)

## day_type・通貨・タイムゾーンの点検 (完了)

- **day_type**: 米国流 (mbta: inactive 270・irregular・dow_* が支配、
  sunday_holiday 不在) も蘭 (ovapi: irregular 1670) も SD1/M10 の設計どおり
  分類される。**en ラベルの1点を修正**: sunday_holiday の en "Sun/Hol" →
  "Sunday" — 分類器は日曜フラグしか見ておらず、祝日を含む示唆は日本の
  データ慣行由来 (ja「日祝」は不変)
- **通貨**: FARE_CHANGED に currency (fare_attributes.currency_type) を
  additive 併記し、表示の円決め打ちを解消 (未指定/JPY は従来表示 = ja 不変)
- **タイムゾーン**: 対応不要 — GTFS の時刻は現地時刻のまま表示し TZ 変換を
  しない仕様 (国際フィードでも正しい)

## 未知ファイルの残差カタログ (完了 — ルール追加はバックログへ)

mbta の残差より: Fares v2 系 (fare_leg_rules 30・fare_products 13・
timeframes 4・areas 7)、MBTA 拡張 (multi_route_trips 15566・
route_patterns 1852・facilities* 830・calendar_attributes 472 ほか)、
transfers 22838 (ovapi では 135656)。いずれも L0 で記帳され残差として
可視 (網羅性は保証済み)。claiming ルールの追加候補としては transfers と
Fares v2 が筆頭 — yamako pass_rules と同じ残差バックログに合流
(detection.md §7)。

すべての DoD を充足: I1 全ペアの記録・地図表示 (基図自動選択)・日本フィード
回帰不変 (G6 スキャン差ゼロ+検証フィード)。
