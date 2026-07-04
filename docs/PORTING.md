# 旧 GTFSDiff からの移植対応表

> 状態: M2 (3e04dce) で移植完了。本表は経緯の記録として維持する。

旧リポジトリ: `/Users/niya/Documents/itolab/2025/gtfsdiff/GTFSDiff` (読み取り専用の参照元。コードの共存はしない)

| 旧 (src/gtfs_diff/) | 新 (src/gtfs_semdiff/) | 移植方針 |
|---|---|---|
| `core.py` (GTFSDataset) | `load/snapshot.py` | ほぼそのまま。day_type 正規化を追加 |
| `repository.py` | `load/repository.py` | ほぼそのまま。動作確認済み API 仕様 |
| `analysis/pattern_clustering.py` | `identity/pattern_clustering.py` | アルゴリズム移植。debug_routes ハードコード・Rich 依存を除去、閾値を config へ |
| `analysis/route_analyzer.py` | `identity/route_family.py` | Route Family 抽出部のみ。差分検出部は events/ のルールに再編 |
| `analysis/stop_analyzer.py` | `identity/stop_clustering.py` | 2段階クラスタリング部のみ。変更検知部は events/rules/stops.py に再編 |
| `analysis/trip_matcher.py` | (原則不使用) | trip 直接マッチングは廃止方針。時刻集合比較 (events/rules/frequency.py) で代替。必要時のみ参照 |
| `analysis/impact_models.py` | `model/event.py` | severity/category 体系の参考。schema は ontology.md 準拠で新設 |
| `analysis/output_formatter.py` | `report/console.py` | 日本語表現・絵文字体系の参考 |
| `models/` `detection/` (統一モデル) | — | **移植しない。** 設計思想 (エンティティ同定) は identity/ が継承済み。二重アーキテクチャの再来を防ぐため参照は最小限に |
| `debug/tree_visualizer.py` ほか | — | 必要になったときに限定的に参照 |

移植時の共通ルール: 閾値リテラルは config/default.toml へ、print/Rich デバッグは logging へ、各移植モジュールに合成データの pytest を新設。
