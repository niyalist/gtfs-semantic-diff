# gtfs-semantic-diff

複数世代の GTFS フィードを比較し、変化を「人間が認識できる意味」——路線廃止・減便・
区間短縮・迂回追加・停留所改称・乗り場変更・運賃改定など——として抽出・レポートする
ツール。[GTFSデータリポジトリ (gtfs-data.jp)](https://gtfs-data.jp) の世代管理 API と
連携し、CLI と Web (自己完結 HTML レポート) の両方で使える。

> **gtfs-semantic-diff** compares two generations of a GTFS feed and reports the
> differences as human-recognizable semantic changes (route discontinued,
> service reduced, stops renamed, timetable diffs in published-timetable
> format, …), with a structural guarantee that every raw difference is
> accounted for. Reports are self-contained HTML files (Japanese-first).
> Built around the Japanese GTFS repository gtfs-data.jp.

## 特徴

- **説明台帳 (explanation ledger)**: 機械的な生差分 (RawDiff) を全列挙し、
  すべてがいずれかのイベントの根拠 (evidence) になるか、未説明残差として報告される。
  被覆率 (explained_ratio) を常に計測・表示するため「何かを見落としていないか」が
  構造的に分かる。
- **ID 非依存の同定**: stop_id / route_id / trip_id が世代間で張り替わっても、
  名称・座標・停車パターン・時刻の内容から「同じもの」を再構成して比較する。
- **認知単位のレポート**: 4部構成 (①フィード全体の変化 ②停留所の変化 ③路線毎の変化
  ④その他) の自己完結 HTML。路線ページは 概要 (leg 単位の停車列・地図) /
  変化のサマリー (Lev.1〜5) / 時間帯別本数 / **出版時刻表形式の新旧差分**
  (旧/新/差分の3切替・曜日タブ・読みにくい表は経由ごとに分冊)。
- **網羅性ビュー (検証モード)**: 全イベントを「レポートのどこに表示されたか」で分類し、
  レポート被覆率を計測。全 RawDiff を GTFS のファイル・行・値の形で列挙し、
  各行から説明イベント → 表示先まで辿れる (3層トレーサビリティ)。
- **決定的ルールベース**: 検出・分類に機械学習や LLM を使わない。閾値はすべて
  `config/default.toml` で明示。同じ入力からは常に同じ結果が出る。
- **JSON が安定インタフェース**: コアは「スナップショット2つ → ChangeEvent JSON」の
  純粋関数。HTML ビューア・Markdown・Web はすべて JSON の消費者。
- **色弱対応**: 全出力で太字・記号 (▲▼・新/廃)・線種・数値を第1チャネルとし、
  色は補強に限る。

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
# gtfs-data.jp から2世代を取得してキャッシュ (~/.cache/gtfs-semantic-diff)
gtfs-semantic-diff fetch --org nagai-unyu --feed Nagaibus

# 比較して HTML レポート (自己完結・単一ファイル) を生成
gtfs-semantic-diff compare --org chitetsu --feed chitetsubus \
    --old prev_2 --new prev_1 --html report.html

# ChangeEvent JSON / Markdown / RawDiff も出力できる
gtfs-semantic-diff compare --org chitetsu --feed chitetsubus \
    -o events.json --report report.md --rawdiffs rawdiffs.json

# ローカル zip 同士の比較 (古い方が先)
gtfs-semantic-diff compare old.zip new.zip --html report.html

# 軽量 HTML (Web 配信と同じ core バンドル — 生差分は件数+サンプル) /
# アプリ+データ分割出力 (http サーバー経由で閲覧)
gtfs-semantic-diff compare old.zip new.zip --html-lite lite.html --html-dir out/

# L1 同定だけを実行し、対応率と confidence 分布を確認
gtfs-semantic-diff identity --org chitetsu --feed chitetsubus
```

- `current` が存在しないフィード (有効期限切れ) は、rid 未指定なら利用可能な最新2世代に
  自動フォールバックする。
- `--config` で閾値設定 TOML を差し替え可能 (既定: `config/default.toml`)。

### Web 版

ブラウザから事業者・世代を選ぶ (または zip をアップロードする) だけでレポートを生成する
Web 版がある (S3 + CloudFront + Lambda のサーバレス構成、`infra/` に AWS CDK 定義、
運用手順は [docs/ops/](docs/ops/))。自分の AWS アカウントにデプロイして使う。

## 出力

- **HTML レポート (推奨)**: 4部構成のレポートモード + 網羅性ビュー (検証モード) の
  自己完結単一ファイル。地図 (地理院タイル + MapLibre) はオンライン時のみ表示。
  ビューアは `viewer/` (Svelte)、ビルド成果物を同梱 (再ビルド: `scripts/build_viewer.sh`)。
- **events.json (正出力)**: `schema_version / feed / events[] / accounting / context`。
  各イベントは英語タイプ ID + 日本語表示名、subject、quantification、
  evidence (根拠 RawDiff ID)、confidence、severity を持つ。
  構造は [docs/design/architecture.md](docs/design/architecture.md) 参照。
- **report.md**: 路線ごと章立ての Markdown レポート。

## どういう変更をどう認識するか

イベントは A(路線)・B(パターン)・C(便数時刻)・D(停留所)・E(カレンダー)・F(運賃・メタ) の
6群・41タイプ。**検出ロジックの網羅的な仕様は
[docs/spec/detection.md](docs/spec/detection.md)** にある (L0 生差分の列挙規則、
L1 同定のスコア式、L2 各ルールの検出条件・evidence 消費規則・閾値の全対応表)。
表示の要件・規則 (方向グループ・分冊・曜日タブ等) は
[docs/design/presentation.md](docs/design/presentation.md)。

```
zip ×2 | gtfs-data.jp API
  → load/      正規化読み込み (day_type 正規化、全 .txt を文字列として保持)
  → diff0/     L0: RawDiff 全列挙 (説明台帳の分母)
  → identity/  L1: 停留所クラスタ / Route Family / 停車パターン / route_group の世代間同定
  → events/    L2: ルールカスケード + 残差集計 → ChangeEvent JSON (正)
  → report/    プレゼンテーションモデル (認知単位) → HTML / Markdown
```

## バージョン

日付ベースの CalVer (`YYYY.M.D.N`、公開時点の日付 + 同日内のリリース通番。例: `2026.7.11.1`)。`pyproject.toml` の `version` が
唯一の定義で、生成される HTML レポートのメタ情報 (`generated_at` とともに) にも
埋め込まれる。

## 状態 (2026-07)

検証フィード (永井運輸・富山地方鉄道・川崎鶴見臨港バスほか計8フィード) で
explained_ratio ≈ 1.0、pytest 157件。富山地鉄の令和8年4月1日改正では公式告知の
主要変更 (フィーダーバス延伸・停留所改称・季節バス終了・通勤帯減便) をすべて検出
([docs/verification/](docs/verification/))。処理時間は最大規模の検証ペア
(30,700 RawDiff) で数秒。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/articles/internals_1_core.md](docs/articles/internals_1_core.md) | **技術解説記事 (前編)**: RawDiff・MatchGraph・TripDelta・ChangeEvent — 説明台帳のコア (実例付き) |
| [docs/articles/internals_2_presentation.md](docs/articles/internals_2_presentation.md) | **技術解説記事 (後編)**: プレゼンテーション層 — 台帳の単位から認知の単位へ |
| [docs/spec/detection.md](docs/spec/detection.md) | **変化検出仕様書** (実装準拠・網羅) |
| [docs/design/presentation.md](docs/design/presentation.md) | レポート表示の要件 (R1〜R18)・改訂履歴 |
| [docs/design/ontology.md](docs/design/ontology.md) | イベントカタログ (設計) |
| [docs/design/architecture.md](docs/design/architecture.md) | アーキテクチャと JSON スキーマ |
| [docs/design/roadmap.md](docs/design/roadmap.md) | マイルストーンと Definition of Done |
| [docs/design/web.md](docs/design/web.md) | Web 版の設計 |
| [docs/verification/](docs/verification/) | 実データ検証ログ (全マイルストーン・全レビューラウンド) |
| [docs/perf/](docs/perf/) | 性能計測記録 |
| [CLAUDE.md](CLAUDE.md) | 設計原則と開発ルール (AI エージェント向け指示書) |

## 開発について

本リポジトリは [Claude Code](https://claude.com/claude-code) を使った人間+AI の
協働で開発している。[CLAUDE.md](CLAUDE.md) がエージェントへの恒常的な指示書
(設計原則・開発ルール) で、進め方は roadmap の Definition of Done 駆動
——「完了」と記録できるのは検証フィードでの実行結果を確認したときのみ。
設計判断・レビューでの指摘と対応・棄却した案は [docs/verification/](docs/verification/)
と各設計文書の改訂履歴に残している。

```sh
.venv.nosync/bin/python -m pytest -q   # 157 tests
.venv.nosync/bin/ruff check src tests
```

- 各検出ルールには「検出条件のドキュメント + 合成 GTFS 単体テスト + 実フィード目視確認例」
  の3点を付ける。
- 閾値のコード内リテラルは禁止。`config/default.toml` に集約する。
- 検出ロジックを変更したら docs/spec/detection.md を、表示規則を変更したら
  docs/design/presentation.md (凍結後の改訂履歴) を同期更新する。

## ライセンス・出典

- コード: [MIT License](LICENSE)
- 地図タイル: [国土地理院タイル](https://maps.gsi.go.jp/development/ichiran.html)
  (レポート内に出典表記)。地図グリフ: Geolonia
- フィードデータ: 各交通事業者が [gtfs-data.jp](https://gtfs-data.jp) で公開する
  オープンデータ。レポートを再配布する場合は各フィードのライセンス表記に従うこと
