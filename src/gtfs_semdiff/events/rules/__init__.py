"""イベント検出ルール群。各モジュールは extract(ctx) を実装する。

CASCADE がカスケード順を定義する (docs/design/ontology.md「抽出カスケード」):
stop 同定 → route family (RENAMED を ADDED/DISCONTINUED より先に) →
パターン照合 → 時刻集合比較 → メタデータ → ID churn。残差は pipeline が集計。
"""

from . import calendars, frequency, metadata, patterns, routes, stops, technical

CASCADE = [stops, routes, patterns, frequency, calendars, metadata, technical]

__all__ = ["CASCADE"]
