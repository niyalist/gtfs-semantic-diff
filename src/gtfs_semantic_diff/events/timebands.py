"""時間帯ビン (config: events.frequency.time_bands) のユーティリティ。

GTFS 時刻は 24 時超え表記 (例 25:30:00) を許す。最初のビン開始より前の
時刻は +24h して再判定する (深夜帯 22:00-29:00 に 01:00 発を入れるため)。
どのビンにも入らない時刻は "other" とする。
"""

from __future__ import annotations

OTHER_BAND = "other"


def parse_gtfs_time(text: str) -> int | None:
    """"HH:MM:SS" → 秒。空・不正は None。"""
    parts = text.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


class TimeBands:
    def __init__(self, band_specs: list[str]):
        self.bands: list[tuple[int, int, str]] = []
        for spec in band_specs:
            start_s, end_s = spec.split("-")
            start = parse_gtfs_time(start_s)
            end = parse_gtfs_time(end_s)
            if start is None or end is None:
                raise ValueError(f"時間帯ビンを解析できません: {spec!r}")
            self.bands.append((start, end, spec))

    def band_of(self, time_text: str) -> str:
        sec = parse_gtfs_time(time_text)
        if sec is None:
            return OTHER_BAND
        for candidate in (sec, sec + 24 * 3600):
            for start, end, label in self.bands:
                if start <= candidate < end:
                    return label
        return OTHER_BAND

    def labels(self) -> list[str]:
        return [label for _, _, label in self.bands] + [OTHER_BAND]
