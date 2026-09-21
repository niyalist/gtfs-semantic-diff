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

## XL3 再実測 (2026-09-22、worker **10240MB** / 15分 / 2026.9.22.1)

AWS サポート回答 (2026-09-22): MemorySize はクォータ対象外で申請不要、
10240MB は全アカウント共通の上限。3008 は初期制限だった (CloudFormation は
10240 をそのまま受理)。再実測のためゲートを暫定 320MB に上げて 4 件を投入
(scripts/web_submit_upload.py — ブラウザと同じ API 経路)。

| feed | stop_times 非圧縮 (new) | 結果 | Duration | ピーク RSS | ジョブ |
|---|--:|---|--:|--:|---|
| trimet | 157MB | ✓ | 427s (天井の 47%) | 4723MB (46%) | anon-6eed91d4355a |
| rome | 237MB | ✓ | **892s (99%)** | 9238MB (90%) | anon-1bbc0bad2a4f |
| mbta | 240MB | ✗ **timeout** | 900s | 8137MB | anon-31681145ddb2 |
| stm | 300MB | ✓ | 822s (91%) | 9439MB (92%) | anon-7c46857c2243 |

- **壁はメモリから時間に移った**。3008MB で 60〜90 秒で OOM だった 4 件が、
  10240MB では 3 件完走。ただし 237MB 以上は 15 分天井の 90〜99% で綱渡り
- **stop_times サイズは時間の予測子として弱い**: mbta (240MB) は stm (300MB)
  より重い。mbta はルール段を 14 分時点で完了 (explained_ratio 0.9527 を
  記録) したあと出力段で天井に到達。イベント数 (mbta 26,788 vs stm 20,685、
  ローカル実測でルール段 616s vs 387s) が効いている。プリフライトは central
  directory しか読まないため、事前に分かるのは stop_times サイズだけ
- XL2 の誠実な失敗が機能: mbta は 905 秒で「制限時間15分またはメモリ上限
  … stop_times 非圧縮 最大 240MB … CLI 版なら」と ja/en で返った
- 副産物: 2026-09-19 のログレベル修正により、worker の pipeline INFO
  (explained_ratio 等) が CloudWatch で読めるようになった。上の「どこまで
  進んだか」はこれで判定した

### 較正: **MAX_STOPTIMES_MB = 200** (handler.py 既定値、2026.9.22.1)

確実圏 (trimet 157MB、時間・メモリとも 50% 未満) と綱渡り圏 (rome 237MB、
時間 99%) の間に安全側で置く。線形内挿で 200MB は約 680s・7GB。237〜300MB
は「成功することもある」規模だが、失敗時に利用者が 16 分待たされる体験
(XL2 の動機) を避けるため受け付けない。CDK 側の環境変数上書きは外し、
handler 既定値の 1 箇所を正とする (再実測時だけ delivery.py で一時上書き)。

### 次に効く手 (XL 残)

- 時間天井に対して vCPU 増は効かなかった (単スレッド)。出力段 (HTML/JSON
  逐次書き出し) の短縮か、ルール段の重い規則の特定が次の伸びしろ
- 国家級 (swiss 1852MB / ovapi_nl 1038MB) は依然桁違い — XL4 (agency 抽出) か CLI
