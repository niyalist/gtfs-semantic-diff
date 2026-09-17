# XL1: Lambda worker の規模限界の実測 (2026-09-17)

MobilityData Summit 前の大規模フィード対応 (roadmap XL トラック) の根拠実測。
都市圏級の国際4フィードを本番 Web (worker Lambda **3008MB** / 15分 /
2026.9.16.4) にアップロード投入した。

## 結果: 4件全て OOM (時間ではなくメモリが壁)

| feed | stop_times 行数 (new) | stop_times 非圧縮 | zip | 結果 (CloudWatch REPORT) |
|---|--:|--:|--:|---|
| trimet | 2.48M | 157MB | 28MB | **Runtime.OutOfMemory** 57s / 3007MB |
| rome | 5.31M | 237MB | 46MB | **Runtime.OutOfMemory** 59s / 3007MB |
| mbta | 5.40M | 240MB | 38MB | **Runtime.OutOfMemory** 88s / 3008MB |
| stm | 7.95M | 300MB | 63MB | **Runtime.OutOfMemory** 58s / 3007MB |

(ジョブ: anon-52741dbf095c / anon-dcda61eccc6f / anon-8c2ecd07b0bd /
anon-400c901ea124、2026-09-17 15時台)

- 全件 **60〜90秒で load/diff0 段階のうちに OOM**。15分の時間天井には
  はるかに届かない — 現行の壁は**メモリのみ**
- 利用者体験の問題 (XL2 の動機を実証): worker は例外ハンドラを走れずに
  死ぬため、ジョブは 16 分間「実行中」のままになり、watchdog が
  「制限時間 (15分) を超えました」という**不正確な**メッセージを出していた
- 成功側の錨: prt (stop_times 1.03M 行 / **76MB**) は 2026-07-24 に本番成功
  (126s、ピーク 2164MB — docs/perf/P2_html_memory.md)。名古屋市営 (国内最大級)
  は 31MB で余裕圏内

## 較正 (XL2 のゲート閾値)

成功 76MB と失敗 157MB の間に安全側で **MAX_STOPTIMES_MB = 100 (MB/世代、
非圧縮)** を設定 (handler.py env、既定値)。gtfs-data.jp 全603フィードの
最大は 8.3MB zip (stop_times 非圧縮でも数十 MB 未満) のため国内利用には
影響しない。

## XL3 (メモリ 3008→10240MB) 後の見込み

prt 実測から線形外挿 (ベース ~0.9GB + 約 17MB RAM / stop_times 1MB):
10240MB なら stop_times ~550MB 相当まで = **stm (300MB) までの都市圏級が
メモリ圏内**に入る見込み。ただし時間側 (ローカル実測 rome 447s・mbta 422s、
Lambda は約×2) が 15 分天井に近く、処理は単スレッドのため vCPU 増の寄与は
限定的 — **XL3 反映後に本表を再実測して閾値を更新する**こと。
国家級 (swiss 1852MB / ovapi_nl 1038MB) はメモリ増強でも桁が届かず、
agency 抽出 (XL4) か CLI が正解のまま。

## XL2 ゲートの本番実証 (2026.9.17.1 デプロイ後、同日)

- trimet 再投入 → **0.5秒で 400**: 「stop_times 非圧縮 new: 157MB /
  old: 175MB、上限 100MB/世代」+ CLI 案内 (ja/en)。従来は16分後に
  「時間超過」という誤報だった
- prt 投入 → 受理・**成功 190.7s / ピーク 1856MB** (job anon-6e2850acc21f)。
  ゲートが正当な規模を弾かないことの錨
- 副作用事故: 初回デプロイで Dockerfile の COPY に preflight.py が漏れ、
  API が約5分 500 (即修正・再デプロイ)。教訓: ランタイム新モジュール追加時は
  Dockerfile の COPY 列を必ず確認

## 測定方法 (再現)

- 投入: scratchpad の xl1_submit.py 相当 — /api/uploads → presigned POST →
  /api/jobs {type:"upload"}
- 計測: CloudWatch `/aws/lambda/...Worker...` の REPORT 行
  (Duration / Max Memory Used / Error Type)
