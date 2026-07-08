"""RawDiff の索引: ルールがエンティティ ID から evidence を引くための逆引き。

キー設計は diff0/engine.py の KEY_COLUMNS に対応する:
- stops.txt      key[0] = stop_id
- routes.txt     key[0] = route_id
- trips.txt      key[0] = trip_id
- stop_times.txt key[0] = trip_id
- shapes.txt     key[0] = shape_id
- calendar / calendar_dates key[0] = service_id
"""

from __future__ import annotations

from collections import defaultdict

from ..model import RawDiff, RawDiffSet


class EvidenceIndex:
    """file → 先頭キー → [RawDiff] の索引。"""

    def __init__(self, rawdiffs: RawDiffSet):
        self.by_file: dict[str, list[RawDiff]] = defaultdict(list)
        self._by_file_key: dict[str, dict[str, list[RawDiff]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for d in rawdiffs.diffs:
            self.by_file[d.file].append(d)
            if d.key:
                self._by_file_key[d.file][d.key[0]].append(d)

    def file_ids(self, filename: str) -> list[str]:
        """ファイル内の全 RawDiff ID。"""
        return [d.rawdiff_id for d in self.by_file.get(filename, ())]

    def for_key(self, filename: str, key0: str) -> list[RawDiff]:
        """先頭キー一致の RawDiff 群。"""
        return self._by_file_key.get(filename, {}).get(key0, [])

    def ids_for_key(self, filename: str, key0: str) -> list[str]:
        return [d.rawdiff_id for d in self.for_key(filename, key0)]

    def ids_for_keys(self, filename: str, keys: list[str] | set[str]) -> list[str]:
        out: list[str] = []
        for k in sorted(keys):
            out.extend(self.ids_for_key(filename, k))
        return out

    def trip_cascade_ids(self, trip_ids: list[str] | set[str]) -> list[str]:
        """trip 群に紐づく trips.txt + stop_times.txt の全 RawDiff ID (上位イベントのカスケード消費用)。"""
        return self.ids_for_keys("trips.txt", trip_ids) + self.ids_for_keys(
            "stop_times.txt", trip_ids
        )
