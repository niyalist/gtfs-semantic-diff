# SD2 検証ログ: 窓内区間対比較 (2026-07-23)

設計: docs/design/service_days.md §2.2 (承認版)。仕様: detection.md §4.5b。
実装: events/windows.py (区間計算・比較ユニット)、events/pipeline.py
(`_resolve_window_scope` + 便世界フィルタ)、events/rules/generations.py
(GENERATION_SCOPE、カスケード最後尾)。ontology v0.2.3 で GENERATION_SCOPE
採録。閾値: `[events.windows] carryover_coverage_min = 0.8` (新設)。

## 検証データと結果 (DoD)

| ケース | SD2 前 (現行) | SD2 後 |
|---|---|---|
| 桑名 実測1: 同居 prev_19 → current (改正後のみ) | **SERVICE_REDUCED 279件 (全便半減の誤説明)**、explained 0.9997 | REDUCED **0件**、本物の差分 (INCREASED 12 等) のみ、**explained 1.0000・残差0** |
| 桑名 実測2: prev_20 (改正前のみ) → 同居 prev_19 | **SERVICE_INCREASED 279件 (全便倍増の誤説明)**、explained 0.9995 | INCREASED **1件**。primary = 7/11〜10/3 で**本物の 7/11 改正** (TIMETABLE_SHIFTED 29・SERVICE_REDUCED 19・churn 53) が出る。「6/1〜7/10 内容同一」も検出。**explained 1.0000・残差0** |
| 伊勢市おかげバス prev_3 → prev_2 (同居・非対称型) | **SERVICE_INCREASED 72件 (倍増)** | INCREASED **0件**。本物の 4/1 改正 (churn 20・REDUCED 6・停留所挿入 3)。explained 0.9998 |
| 名古屋 (年次アーカイブペア) | — | イベント **完全一致** (退化。特定日型を除外しない規則で担保) |
| 臨港 | — | イベント **完全一致** (退化) |
| 佐賀 (1月→4月、旧側が世代同梱の実例) | REDUCED 156 / INCREASED 12 | 期限切れ・後継ありの「1_平日運行」2便のみ除外。±1件の重複計上解消 (REDUCED 155 / INCREASED 13)。**後継のない三瀬神埼線は除外されず**従来比較を維持 |
| prt (窓が交差しない隣接世代ペア) | — | scope=None (完全退化。SD1 の結果と同一) |
| 合成テスト | — | tests/test_generations.py 4件 (両方向・同居×同居圧縮・期間端ずれの退化) + 全222件通過 |

routes_jp.txt の残差14件 (世代サフィックス付き route_id の付随行) は
TECHNICAL_ID_CHURN の evidence に routes_jp を同乗させて解消 (一般的改善)。

## 実装で確定した規則 (設計からの学び)

1. **退化の第1防衛線 = 上位集合ユニット**: 期間端が揃っていないだけの通常
   フィード (学期 service 等) は、全ユニットを包含するユニットが存在し全便
   比較に退化する。
2. **特定日型は除外しない**: 名古屋の年次ペアでは「キントレ」等の特定日
   service が窓外に落ちるが、特定日世界同士の比較 (現行) が人の認識に合う。
   除外対象は週次レギュラー型のみ。
3. **後継条件は family ブロック粒度・カバー率閾値**:
   - route_id は世代サフィックスで張り替わる (桑名) → 内容主導の family で判定
   - family 名も改正で切れる (伊勢市「環状線 → 右回り/左回り」) → M9 の
     世代間対応成分 (route_group ブロック) 粒度 + カバー率 ≥ 0.8
   - 後継のない路線 (佐賀の三瀬神埼線 — 集約フィードで路線ごとに時刻表の
     掲載期限が違う) は除外しない = 「旧側の最後に知られたダイヤ vs 新側」の
     比較を維持
4. **持ち越し世代に厳密な内容同一を要求しない**: 伊勢市では持ち越し世代にも
   乗り場 ID 張り替えが入っていた (12便)。同一性でなく後継カバー率で判定。

## 既知の限界 (記録)

- T3 (同一 day_type 内の季節分割) は対象外のまま (service_days.md §8)。
- identity (M9) は全便で対応を作るため、持ち越し世代と名前一致すると改正側の
  再編が粗くなる (伊勢市の環状線分割が ROUTE_ADDED×2 に落ちる。倍増の解消が
  主眼のため許容)。スコープ解決後の identity 再構築は将来課題。
- レポート (viewer) はまだ comparison_scope を表示しない — 第1部への注記と
  カレンダービューは SD3/SD4。
