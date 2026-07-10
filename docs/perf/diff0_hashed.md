# diff0 ハッシュ突合の二次爆発の修正 (2026-07-10)

## 症状

比較が実質終わらないフィードの報告 (ユーザー: 山交バス・産交バス。
Web ジョブはタイムアウト/OOM でも status=running のまま残り「終わらない」に見える)。

## 原因 (山交バス yamakobus prev_1→current で特定)

`diff0/engine.py _diff_rows_hashed` (主キー重複ファイルのフォールバック突合) で、
**Counter の差 (全行走査 O(N)) をループの中で毎回再計算**していた:

```python
for row in sorted(old_counter - new_counter):
    count = (old_counter - new_counter)[row]   # ← 1行ごとに O(N) の再計算
```

計算量は O(差分行数 × 全行数)。山交は stop_times 3.2万行・約3年分の全面改正で
差分行数 ≈ 全行数となり、実測でスタックダンプ (faulthandler) が
`Counter.__sub__` を指し続ける実質ハング (2分でも diff0 を抜けない) だった。

## 修正と実測

差を1回だけ計算 (出力・順序は完全に同一):

| フィード | ペア | before | after |
|---|---|---|---|
| 山交バス (stop_times 3.2万行、RawDiff 24.7万) | prev_1→current | 実質ハング (>数分、CPU 97%) | **全パイプライン 6.1秒 / CLI+HTML 5.5秒** |
| 産交バス (stop_times 54.7万行×2) | prev_1→current | — | 29秒 (956MB peak)。※産交の各世代は同一データで diff は小さい |

回帰: 永井 1.0000 (99イベント)・徳島 1.0000 (1011イベント) 不変。pytest 175件。

## あわせて実施した Web 側の対策

- worker Lambda を 2048→4096MB (Lambda は memory 比例で vCPU も増える。
  産交級のフィードの余裕)
- **running スタック対策**: worker が Lambda タイムアウト/OOM で死ぬと例外
  ハンドラが走れず status=running が残る → status API が経過時間 (>16分) で
  failed と判定してポーリングを止める (infra/runtime/handler.py)

## 副次的な発見 (別課題)

山交 prev_1→current の explained_ratio は 0.8484。残差の 37,037件は
`pass_rules.txt` (GTFS-JP 圏外の独自ファイル) — L0 が全 .txt を読む設計 (網羅性)
どおりで、これを説明するルール (未知ファイルの変更をファイル単位で束ねる
イベント) は未実装。残差カタログ育成の入力として記録する。
