# gtfs-semdiff

複数世代の GTFS フィードを比較し、変化を「人間が認識できる意味」——路線廃止・減便・
区間短縮・迂回追加・乗り場変更・運賃改定など——の **ChangeEvent** として抽出する
CLI ツール。[GTFSデータリポジトリ (gtfs-data.jp)](https://gtfs-data.jp) の世代管理 API と連携する。

特徴:

- **説明会計 (explanation accounting)**: 機械的な生差分 (RawDiff) を全列挙し、
  すべてがいずれかのイベントの根拠 (evidence) になるか、未説明残差として報告される。
  被覆率 (explained_ratio) を常に計測・表示するため「何かを見落としていないか」が構造的に分かる。
- **ID 非依存の同定**: stop_id / route_id / trip_id が世代間で張り替わっても、
  名称・座標・停車パターン・時刻の内容から「同じもの」を再構成して比較する。
- **決定的ルールベース**: 検出・分類に機械学習や LLM を使わない。閾値はすべて
  `config/default.toml` で明示。同じ入力からは常に同じ結果が出る。
- **JSON が安定インタフェース**: コアは「スナップショット2つ → ChangeEvent JSON」の
  純粋関数。Markdown レポートや将来の Web ビューアはすべて JSON の消費者。

## インストール

Python 3.11+ (開発は 3.14)。

```sh
uv venv .venv.nosync --python 3.14   # リポジトリが iCloud 同期下にある場合 .nosync 必須 (下記)
ln -s .venv.nosync .venv
uv pip install -e '.[dev]' --python .venv.nosync/bin/python
```

> **注意 (macOS + iCloud)**: リポジトリが `~/Documents` 等 iCloud 同期下にある場合、
> venv を `.venv` 直下に作ると iCloud が site-packages の `.pth` に hidden フラグを
> 復元し続け、Python 3.14 がそれを無視するため import が壊れる。`*.nosync` ディレクトリ
> は iCloud が同期しないため、この構成を使う。

## 使い方

```sh
# gtfs-data.jp から2世代を取得してキャッシュ (~/.cache/gtfs-semdiff)
gtfs-semdiff fetch --org nagai-unyu --feed Nagaibus

# 比較して ChangeEvent JSON + Markdown レポートを出力 (既定: prev_1 → current)
gtfs-semdiff compare --org chitetsu --feed chitetsubus \
    --old prev_2 --new prev_1 \
    -o events.json --report report.md --rawdiffs rawdiffs.json

# ローカル zip 同士の比較 (古い方が先)
gtfs-semdiff compare old.zip new.zip -o events.json

# L1 同定だけを実行し、対応率と confidence 分布を確認
gtfs-semdiff identity --org chitetsu --feed chitetsubus
```

- `current` が存在しないフィード (有効期限切れ) は、rid 未指定なら利用可能な最新2世代に
  自動フォールバックする。
- `--config` で閾値設定 TOML を差し替え可能 (既定: `config/default.toml`)。

## 出力

- **events.json (正出力)**: `schema_version / feed / events[] / accounting / context`。
  各イベントは英語タイプ ID + 日本語表示名、subject (対象)、quantification (数値)、
  evidence (根拠 RawDiff ID)、confidence、severity (major/minor/info) を持つ。
  トップレベル構造は [docs/design/architecture.md](docs/design/architecture.md) 参照。
- **report.md**: 京都市交通局別紙風の5章構成 — 表紙 / 全体サマリ (major 一覧) /
  路線別詳細 (停車パターン変化・時間帯別本数表 旧→新) / 停留所の変更 / データ検証
  (explained_ratio・ID 張り替え・未説明残差の全件)。

## どういう変更をどう認識するか

イベントは A(路線)・B(パターン)・C(便数時刻)・D(停留所)・E(カレンダー)・F(運賃・メタ) の
6群・41タイプ。**検出ロジックの網羅的な仕様は
[docs/spec/detection.md](docs/spec/detection.md)** にある (L0 生差分の列挙規則、
L1 同定のスコア式、L2 各ルールの検出条件・evidence 消費規則・閾値の全対応表)。
設計時のイベントカタログは [docs/design/ontology.md](docs/design/ontology.md)。

処理の流れ:

```
zip ×2 | gtfs-data.jp API
  → load/      正規化読み込み (day_type 正規化、全 .txt を文字列として保持)
  → diff0/     L0: RawDiff 全列挙 (説明会計の分母)
  → identity/  L1: 停留所クラスタ / Route Family / 停車パターンの世代間同定 (MatchGraph)
  → events/    L2: ルールカスケード (D→A→B→C→E→形状→F→ID churn) + 残差集計
  → ChangeEvent JSON → report/ (Markdown)
```

## 状態 (2026-07)

roadmap の全マイルストーン M0–M5 完了。検証フィード3件
(永井運輸・富山地方鉄道バス・川崎鶴見臨港バス) で explained_ratio 1.0000、
処理時間は最大 30,700 RawDiff のペアで約2秒 ([docs/perf/](docs/perf/))。
富山地鉄の令和8年4月1日改正では、公式告知・報道の主要変更 (フィーダーバス延伸、
停留所改称、季節バス終了、通勤帯減便) をすべて対応イベントとして検出
([docs/verification/](docs/verification/))。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/spec/detection.md](docs/spec/detection.md) | **変化検出仕様書** (実装準拠・網羅) |
| [docs/design/ontology.md](docs/design/ontology.md) | イベントカタログ (設計) |
| [docs/design/architecture.md](docs/design/architecture.md) | アーキテクチャと JSON スキーマ |
| [docs/design/roadmap.md](docs/design/roadmap.md) | マイルストーンと Definition of Done |
| [docs/verification/](docs/verification/) | 各マイルストーンの実データ検証ログ |
| [docs/perf/](docs/perf/) | 性能計測記録 |
| [CLAUDE.md](CLAUDE.md) | 設計原則と開発ルール |

## 開発

```sh
.venv.nosync/bin/python -m pytest -q   # 99 tests
.venv.nosync/bin/ruff check src tests
```

- 各検出ルールには「検出条件のドキュメント + 合成 GTFS 単体テスト + 実フィード目視確認例」
  の3点を付ける (CLAUDE.md 開発ルール)。
- 閾値のコード内リテラルは禁止。`config/default.toml` に集約する。
