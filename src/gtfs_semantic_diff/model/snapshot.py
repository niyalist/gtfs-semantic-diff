"""GtfsSnapshot: 正規化済み GTFS 1世代分のインメモリ表現。

読み込みロジックは load/ 側 (load.loader) が担い、このモジュールは
データ構造と参照系メソッドのみを持つ。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class SnapshotMeta:
    """スナップショットの出自情報。ローカル zip の場合は path のみ埋まる。"""

    source: str = ""  # ローカルパスまたはダウンロード URL
    org_id: str = ""
    feed_id: str = ""
    rid: str = ""  # current / prev_1 / ... (gtfs-data.jp の世代 ID)
    from_date: str = ""  # YYYY-MM-DD (gtfs-data.jp が返す有効期間)
    to_date: str = ""

    def label(self) -> str:
        """ログ・レポート用の短い識別ラベル。"""
        if self.rid:
            return f"{self.org_id}/{self.feed_id}@{self.rid}"
        return self.source or "(unknown)"


@dataclass
class GtfsSnapshot:
    """GTFS 1世代分。

    - tables: ファイル名 (拡張子なし, 例 "stops") → DataFrame。
      全列 str dtype・欠損は空文字列 "" に正規化済み (L0 diff の前提)。
    - day_types: service_id → day_type ラベル ("weekday" / "saturday" /
      "sunday_holiday" / "weekend" / "daily" / "dow_XXXXXXX" (曜日指定) /
      "irregular" (特定日) / "inactive" (運行日なし) — load/day_types.py)
    """

    meta: SnapshotMeta
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    day_types: dict[str, str] = field(default_factory=dict)

    def table(self, name: str) -> pd.DataFrame | None:
        return self.tables.get(name)

    def has_table(self, name: str) -> bool:
        return name in self.tables

    def table_names(self) -> set[str]:
        return set(self.tables.keys())

    def row_counts(self) -> dict[str, int]:
        return {name: len(df) for name, df in sorted(self.tables.items())}

    def summary(self) -> str:
        trips = self.tables.get("trips")
        stops = self.tables.get("stops")
        routes = self.tables.get("routes")
        return (
            f"{self.meta.label()}: {len(self.tables)} tables, "
            f"{len(routes) if routes is not None else 0} routes, "
            f"{len(stops) if stops is not None else 0} stops, "
            f"{len(trips) if trips is not None else 0} trips"
        )
