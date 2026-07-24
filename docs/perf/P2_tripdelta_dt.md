# 便対応の Δt 前計算 — P2/IN-2 (2026-07-24)

## 背景

IN-1 (ルール段の O(n²) 2件、docs/perf/P2_rules_hotspots.md) 解消後の最大支配項は
便対応 (tripdelta): mbta 792s / rome 401s / trimet 190s。cProfile (trimet) で
**`dt_shared_minutes` が段のほぼ全て (785s/798s、プロファイラ込み) を占め、
内部の `parse_gtfs_time` が 4.66 億回**呼ばれていると特定。

原因: 候補ペア毎に dt_shared_minutes を素評価しており、同じ trip の時刻文字列の
パースと初出辞書の構築を「その trip が候補対に現れる回数」だけ繰り返していた
(trimet で 432 万ペア)。なお P1 で疑っていた LCS キャッシュのタプルハッシュは
実測 4.9s で問題なし。

## 修正 (出力不変)

`events/tripdelta.py`:

- `_time_profile(t)`: trip 毎に1回だけ (基底停留所 → 初出の発時刻秒) 辞書と
  始発秒を前計算 (パース不能は None — 従来の読み飛ばしと同義)
- `_dt_shared_from(...)`: 前計算済み辞書同士の整数演算で Δt_shared を計算。
  初出選択・None 読み飛ばし・中央値・フォールバック (始発差) の意味は
  従来の `dt_shared_minutes` と厳密に同一 (median は同一多重集合なので同値)
- `dt_shared_minutes` は仕様の定義関数として残置 (前計算版のラッパ)

## 実測 (I1 データセット、ローカル Mac、caffeinate 付き)

collect+scope+tripdelta 段 (「前」は IN-1 修正後 = c8648b5):

| feed | 前 | 後 | 全体所要 (I1 初回計測 → IN-1 → IN-2) |
|---|---|---|---|
| trimet | 190s | **38.8s** (4.9x) | 273s → 260s → **111s** |
| mbta | 792s | **168.4s** (4.7x) | 1010s → 932s → **314s** |
| rome | 401s | **81.8s** (4.9x) | 1523s → 640s → **320s** |

イベント数・explained_ratio は全フィードで I1 台帳と一致
(mbta 18,274 / 0.9958、rome 11,015 / 0.9834)。

国家規模 (I1 で >1800s タイムアウト、IN-6 で当面対象外):

| feed | 結果 |
|---|---|
| swiss | **初完走**: 総計 1904s (32分) — load 269 / diff0 319 (RawDiff **5,250万**) / identity 101 / tripdelta 862 / rules 239 / 残差 77。events 87,035、explained **0.9942** |
| ovapi_nl | (計測中) |

## 出力の同一性

- イベント JSON (全フィールド) を修正前後でバイト比較:
  **trimet (4535件)・名古屋・桑名 (SD2 scope 発動経路) すべて完全一致**
- pytest 224件・ruff 通過

## 残るコスト構造 (参考)

- diff0 が新たな最大支配項に近づく (rome 107s / mbta 76s)。RawDiff 1000万件級の
  列挙そのものなので、IN-3 (メモリ) と合わせて扱うのが筋
- tripdelta 残部は候補対列挙 O(|olds|×|news|) の LCS ゲート前走査と
  candidates 構築。ブロック内前絞り (時刻帯バケツ等) が次の一手だが、
  受理集合が変わりうるため出力不変では済まない — 導入するなら config ゲート +
  別途議論 (roadmap P トラック方針)
