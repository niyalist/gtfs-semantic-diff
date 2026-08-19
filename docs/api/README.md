# gtfs-semantic-diff を外から使う — 案内

このディレクトリは、gtfs-semantic-diff を**プログラム・AI・外部システムから**
使う人のためのドキュメントです。人間が読むことと、LLM にそのまま渡して
文脈にすることの両方を想定しています。仕様の正確な定義は
[reference.md](reference.md) にあります。

## このツールは何をするものか

複数世代の GTFS フィード (バスのダイヤデータ) を比較し、変化を
**人間が認識できる意味** — 路線廃止、減便、経由変更、停留所改称、乗り場変更
など **44種類の ChangeEvent** — として抽出します。特徴は**説明台帳**:
2世代間の生の差分 (ファイル・フィールド単位の全件) は、必ずいずれかの
イベントの証拠 (evidence) に紐づくか「未説明の残差」として計上され、
被覆率 (explained_ratio) が常に出ます。**どこまで説明できて何が説明できて
いないかが数値で保証される**のが、単純な diff ツールとの違いです。

検出は決定的ルールベースで、LLM や機械学習はコアに入っていません。
同じ入力からは常に同じ出力が出ます。閾値はすべて設定ファイルにあります。

## 何ができるか (ユースケース)

- **データのエラーチェック**: 残差 (UNEXPLAINED_RESIDUAL) や
  ID 張り替え (TECHNICAL_ID_CHURN)、説明台帳の数値から、フィード作成時の
  ミス (service_id の付け間違い、停留所の重複登録など) を洗い出す。
- **改正内容の要約・告知文づくり**: イベントと数値 (どの路線が何便減ったか、
  どの停留所が改称されたか) を素材に、人間向けの文章を書く。事実・数値は
  本ツールの出力から、文章化は利用側 (人間や LLM) で、という役割分担。
- **公式告知との突合**: 事業者の改正告知に書かれた項目が、データにも
  反映されているか (またはデータにしかない変化がないか) を照合する。
- **研究・分析**: 減便・路線再編・運行日区分の変化を、地域横断・時系列で
  集計する。運転手不足・交通空白などの研究の入力になる。

## 出力の3層 — どれを使うか

| 層 | 中身 | 向く用途 | 大きさの目安 |
|---|---|---|---|
| digest | 全体要約+路線毎の要約行。ID なし | 翻訳・告知・突合。LLM に最初に渡すもの | 数十〜数百 KB |
| events.json | ChangeEvent 全件+証拠+説明台帳 | エラーチェック、プログラム連携。**安定インタフェース** | 〜数十 MB |
| rawdiffs.json | 生差分の全件 (L0) | 残差の精査、完全な検証 | 〜数百 MB |

原則: **広く浅い用途は上の層から、狭く深い用途ほど下の層へ**。
HTML レポート (ビューア) は人間の閲覧用で、その内部データ (bundle) は
安定インタフェースではありません — プログラムからは events.json を使って
ください。

## クイックスタート

### CLI (ローカル)

```bash
# gtfs-data.jp から世代を取って比較 (zip を直接渡すこともできる)
gtfs-semantic-diff compare --org nagai-unyu --feed Nagaibus \
    --old prev_2 --new prev_1 \
    --digest digest.md -o events.json --html report.html
```

- `digest.md` — AI 向けダイジェスト (LLM にそのまま渡せる要約。`--digest-json` で JSON)
- `events.json` — 機械可読の全イベント+説明台帳
- `report.html` — 自己完結ビューア (ブラウザで開く)

1路線を深掘りするなら `--digest-route "路線名" --digest route.md`
(変化した便の一覧が trip_id 付きで出る)。

ローカルの zip 2つを比較するなら `compare old.zip new.zip` (古い方が先)。

### Web API (https://diff.gtfs.jp/)

```bash
# 1) 比較ジョブを投入 (uid は gtfs-data.jp の世代のフル UUID)
curl -X POST https://diff.gtfs.jp/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"type":"gtfs_data_jp","org":"nagai-unyu","feed":"Nagaibus",
       "old_uid":"<full-uid>","new_uid":"<full-uid>"}'
# → {"job_id": "<pair>", "status_url": "/api/jobs/<pair>"}

# 2) 完了をポーリング (succeeded になるまで)
curl https://diff.gtfs.jp/api/jobs/<pair>

# 3) 成果物 (版付き・不変)
#    レポート:      https://diff.gtfs.jp/r/<pair>.html
#    ダイジェスト:   https://diff.gtfs.jp/r/<pair>.digest.md (最新版。LLM にはまずこれ)
#    イベント JSON: https://diff.gtfs.jp/r/<pair>/v/<版>.events.json
#    生差分 JSON:   https://diff.gtfs.jp/r/<pair>/v/<版>.rawdiffs.json
```

uid の探し方 (gtfs-data.jp の世代一覧):

```bash
curl "https://diff.gtfs.jp/api/gtfs/feeds?pref=10"          # フィード一覧 (県別)
curl "https://diff.gtfs.jp/api/gtfs/files?org=nagai-unyu&feed=Nagaibus"  # 世代一覧
```

## ユースケース別レシピ

### エラーチェック (データ作成者)

1. events.json の `accounting.explained_ratio` を見る。1.0 に近いほど
   全差分が意味づけできている。`residual_breakdown_by_file` で残差の
   所在 (どのファイルか) を確認。
2. `type == "UNEXPLAINED_RESIDUAL"` と `TECHNICAL_ID_CHURN` のイベントを
   列挙する。ID 張り替えが大量にあるのは、内容が同じなのに trip_id や
   service_id を作り直している兆候 (それ自体は無害だが、意図的か確認に値する)。
3. 各イベントの `evidence` (rawdiff ID のリスト) から rawdiffs.json の
   該当行に遡ると、GTFS のどのファイル・どの行が根拠か分かる。

### 改正の要約 (翻訳)

1. events.json を `severity` (major > minor > info) と `type` で絞る。
   路線・停留所の名前は `subject` に入っている (表示名は
   `display_name_ja` / `display_name_en`)。
2. 数値は `quantification` から取る (便数、率、日数など)。**文章を生成する
   側は数値を再計算しない** — 事実は必ず出力から引く。
3. digest (`--digest`) はこの手順を1ファイルに前処理したもの。まずこれを使う。

### 突合 (公式告知との照合)

告知の項目 (例: 「4月1日から○○線を減便」) ごとに、events.json から
該当路線の SERVICE_REDUCED / PATTERN_TRUNCATED 等を探す。逆方向
(データにあって告知にない変化) は severity=major のイベントを列挙して
告知と照らす。

## AI に渡すときの推奨

- レポート URL (`…/r/<pair>.html`) をそのまま AI に渡しても、HTML の
  `link rel="alternate"` とサイトの `/llms.txt` から digest に誘導されます。
  確実なのは最初から `…/r/<pair>.digest.md` を渡すこと。

- まず digest (`--digest out.md`) を渡し、深掘りが要るときだけ
  events.json の該当部分を渡す。events.json 全体は大規模フィードで
  数十 MB になるので、`type` や `subject` でフィルタしてから渡すこと。
- イベント型の意味は [reference.md](reference.md) の型カタログを併せて
  渡すと解釈が安定する。
- 事実・数値は出力の JSON からのみ引用させ、推測での補完をさせない
  (本ツールの設計原則と同じ)。

## 制約・注意

- 比較は常に「旧→新」の2世代ペア。多世代タイムラインは未対応。
- Web のジョブ実行は計算資源を使うため、大量の自動投入はしないこと
  (コストガードがあり、超過時は拒否される)。研究等でまとまった量を
  回したい場合は CLI をローカルで使うのが確実。
- 出力の日本語はデータ由来 (停留所名・路線名)。イベント型 ID と JSON の
  キーは英語で安定。
