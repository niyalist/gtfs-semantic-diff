# アーキテクチャ

## 全体データフロー

```
[入力] zip x N | gtfs-data.jp API (current/prev_k)
   │
   ▼
load/          GtfsSnapshot: 正規化済み読み込み (pandas DataFrame 群 + インデックス)
   │           - calendar → day_type (weekday/saturday/holiday/...) への正規化
   │           - 文字コード・BOM・型の吸収
   ▼
diff0/         RawDiff 全列挙 (L0)
   │           - ファイル単位 → 行単位 → フィールド単位
   │           - 各 RawDiff に安定 ID を付与 (rawdiff_XXXXX)
   │           - この時点では ID をキーにした素朴な突合で良い
   ▼
identity/      世代間同定 (L1) — ID に依存しない「同じもの」の再構成
   │           - stop_clusters: 世代内クラスタリング → 世代間リンク
   │           - route_families: 路線名ベースのグループ化 + パターン類似照合
   │           - pattern_clusters: 停車パターンの LCS 類似度クラスタリング
   │           - service_patterns: day_type 正規化
   │           出力: MatchGraph (old entity ↔ new entity, confidence 付き)
   ▼
events/        ChangeEvent 抽出 (L2)
   │           - ルールカスケード (ontology.md の依存順)
   │           - 各ルールは MatchGraph + Snapshot + RawDiff を読み、
   │             ChangeEvent を emit し evidence として RawDiff を消費
   │           - 最後に accounting: 未消費 RawDiff → UNEXPLAINED_RESIDUAL
   ▼
[正出力] ChangeEventSet JSON  ←←← 安定インタフェース。ここまでがコア
   │
   ▼
report/        消費者: Markdown レポート生成 (京都市別紙風・路線ごと章立て)
cli.py         消費者: コンソールサマリ
(将来)         Web ビューア / GUI / 他システム組込み — すべて JSON を読む
```

## モジュール構成

```
src/gtfs_semantic_diff/
├── model/        # データクラス: GtfsSnapshot, RawDiff, MatchGraph, ChangeEvent
├── load/         # zip/dir 読み込み, repository.py (gtfs-data.jp API クライアント)
├── diff0/        # L0 網羅diff エンジン
├── identity/     # stop_clustering.py, route_family.py, pattern_clustering.py, calendar_norm.py
├── events/       # rules/ 配下にイベントタイプごとの検出ルール, accounting.py
├── report/       # markdown.py (renderer), console.py
├── config.py     # config/default.toml の読み込み
└── cli.py        # click エントリポイント
```

設計上の要点:

- **ルールはプラグイン形式**: `events/rules/` の各モジュールが `Rule` プロトコル (`applies_to`, `extract(ctx) -> list[ChangeEvent]`) を実装。カスケード順序は依存宣言から解決。ルール追加が UNEXPLAINED_RESIDUAL を減らす、という開発ループを回しやすくする。
- **MatchGraph は仮説管理**: 対応付けは (old, new, confidence, method) のエッジ。低 confidence の対応も破棄せず保持し、下流ルールの整合で昇格/棄却。
- **多世代 (N≥3)**: コアは隣接ペア比較。CLI 層で prev_k チェーンを順に比較し、イベント列を時系列に連結する(ROUTE_ADDED→即DISCONTINUED のような揺らぎ検出は将来課題として events/timeline.py に置く)。

## CLI 想定インタフェース

```
# gtfs-data.jp から取得して比較 (直近2世代)
gtfs-semantic-diff compare --org nagai-unyu --feed Nagaibus

# 世代指定・多世代
gtfs-semantic-diff compare --org nagai-unyu --feed Nagaibus --from prev_2 --to current

# ローカルファイル
gtfs-semantic-diff compare old.zip new.zip

# 出力
gtfs-semantic-diff compare ... -o events.json --report report.md
```

## ChangeEventSet JSON トップレベル

```json
{
  "schema_version": "0.2",
  "feed": {"org_id": "...", "feed_id": "...", "old_rid": "prev_1", "new_rid": "current"},
  "generated_at": "...",
  "config_snapshot": {...},
  "events": [...],
  "accounting": {          // 説明台帳のサマリ (キー名は安定インタフェースのため旧称 accounting のまま)
    "rawdiff_total": 12345,
    "explained": 12290,
    "explained_ratio": 0.9955,
    "residual_breakdown_by_file": {"stop_times.txt": 40, "...": "..."}
  }
}
```

## Markdown レポート構成 (report/markdown.py)

1. 表紙: フィード名・比較世代・有効期間
2. 全体サマリ: 新設/廃止路線、停留所新設/廃止/改称、運賃改定、major イベント一覧
3. 路線ごとの章 (route_group 単位、京都市交通局別紙風): 構成系統と凝集度、系統図的な停車パターン変化、時間帯別本数表 (旧→新)、当該路線の全イベント、低凝集 family の運行系統構成。末尾に**変更のない路線の一覧** (網羅性の明示 — 「載っていない」と「変更なしと確認した」を区別する)
4. 停留所の章: 乗り場変更・移設・改称の一覧表
5. データ検証章: TECHNICAL_ID_CHURN の要約、FEED_VALIDITY_CHANGED、explained_ratio、UNEXPLAINED_RESIDUAL の全件
