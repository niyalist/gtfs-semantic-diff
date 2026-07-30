# EXP1 検証ログ: コーパス悉皆計測 (論文評価章)

実施日: 2026-07-30 / スクリプト: scripts/experiment_survey.py /
データ: data/experiments/pilot.csv, corpus.csv (gitignore 済み)

## 方法

- 対象: gtfs-data.jp 全596フィードの直近2世代ペア + ローカル参照点2
  (名古屋 年次アーカイブ 20250329→20260328、MBTA old/new)。
- 計測: 入力規模 (行数・クラスタ/family/group/パターン数・Σblock²)、
  出力 (RawDiff内訳・イベント種別・explained_ratio・残差のファイル別内訳)、
  フェーズ別時間 (load/diff0/identity/tripdelta/rules)。フェーズ計測は
  pipeline 名前空間の計時ラッパ (コア無変更・出力バイト不変)。
- 決定性: 全ペア2回実行、generated_at 除外のイベントJSON SHA-256 比較。

## 結果サマリ

- 596 中: 世代2つ未満 117 / 実行成功 476 / 失敗 3 (必須ファイル欠落1、
  shapes カラム欠落1、CSV構文エラー1 — いずれも入力データ不備)。
- **決定性: 476/476 でハッシュ一致。**
- **被覆率**: 中央値 1.0。=1.0 が 312 (66%)、≥0.999 が 374、≥0.99 が 429 (90%)、
  <0.9 が 11。生差分加重の全体被覆率 **0.987** (総生差分 4,026,560 / 残差 51,750)。
  最小 0.256 は生差分39件の小分母 (TownFerryShingu)。
- **残差の内訳** (ファイル別): pass_rules.txt 37,043 (実質 YAMAKOBUS 1フィード。
  GTFS-JP 定期券拡張 — **未採録語彙の最大候補、残差全体の72%**)、
  stop_times.txt 9,848 (上位3フィード tosaden 市電 2,387 / SHONAIKOTSU 2,305 /
  minamichita 2,012 で68%)、stops.txt 3,655 (SHONAIKOTSU 981 ほか)、
  trips.txt 723。→ 残差は少数原因に集中し、次の採録対象が集計から特定できる
  (説明台帳の育成ループの大規模実証)。stop_times / stops 系の上位フィードは
  個別精査の価値あり (day_type 跨ぎ・同定漏れの可能性)。
- **性能**: 中央値 0.12s / p90 0.56s / 国内最大 21.1s (sankobus、stop_times
  181万行)、MBTA 299s。log-log 回帰: t_total〜zip_bytes R²=0.78、
  t_total〜stop_times行数 R²=0.64、**t_tripdelta〜Σblock² R²=0.80** (slope 0.51)。
  支配フェーズは規模で交代: 行数大 → diff0 (sankobus 56%)、ブロック大 →
  tripdelta (MBTA 52%)。bulk 集約の発動は 3 フィード。

## 論文への反映

- 図: outputs 側 its106_paper/figures/ratio_dist.pdf, perf_scaling.pdf
  (生成コードは本計測の bash セッション内 — 必要なら scripts/ に昇格)
- 評価章 §大規模計測、概要・序論・結論の数値を本ログに基づき更新 (2026-07-30)。

## フォローアップ候補

1. pass_rules / pass_attributes の消費ルール採録 (F群、ファイル単位) —
   残差72%が解消する見込み。
2. stop_times 残差上位 (tosaden 市電・SHONAIKOTSU・minamichita) の個別精査。
3. 失敗3件はローダの頑健化候補 (欠落カラムのフォールバック等)。
