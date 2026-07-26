"""calendar_dates 専用 service の dow 規則性調査 (根室 落石線問題の一般化)。

問題: _classify_dates は 平日/土/日 の3ビン多数決のみで dow_XXXXXXX を
出せない。同じ「毎週水曜運行」でも calendar フラグなら dow_0010000、
calendar_dates 列挙なら weekday になり、表現の違いがラベルの違いになる
(根室交通 特別ダイヤ１ = 毎週水曜 → weekday → 平日ラベルが世界4分裂)。

提案規則 (プロトタイプ): 日付集合から dow プロファイルを検出する。
  - span 内の各曜日の出現率 coverage[dow] = 運行日数 / span 内のその曜日数
  - coverage >= dow_on の曜日を「活性」とし、活性曜日外の日 (祝日等の
    はみ出し) が stray_max 以下なら、活性曜日集合をフラグ相当として
    _classify_day_flags と同じ写像でラベル化
  - 検出できなければ現行の3ビン多数決へフォールバック (挙動不変)

このスクリプトは提案規則を全手元フィードに適用し、ラベルが変わる
service を列挙する (実装変更はしない)。
"""
from __future__ import annotations

import datetime
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.load import load_snapshot  # noqa: E402
from gtfs_semantic_diff.load.day_types import (  # noqa: E402
    _CALENDAR_DAY_COLUMNS,
    _classify_day_flags,
)

DOW_ON = 0.6        # この出現率以上の曜日を活性とみなす
STRAY_MAX = 0.1     # 活性曜日外の日の許容率 (祝日振替等)
DAILY_MIN = 0.9     # 全曜日活性 (=daily) と断定する最小出現率 (保守的閾値)


def dow_label(dates: list[str]) -> tuple[str | None, dict]:
    ds = sorted({d for d in dates})
    if len(ds) < 3:
        return None, {}
    days = [datetime.date(int(t[:4]), int(t[4:6]), int(t[6:8])) for t in ds]
    lo, hi = days[0], days[-1]
    total = [0] * 7
    d = lo
    one = datetime.timedelta(days=1)
    while d <= hi:
        total[d.weekday()] += 1
        d += one
    hit = [0] * 7
    for x in days:
        hit[x.weekday()] += 1
    cov = [h / t if t else 0.0 for h, t in zip(hit, total)]
    active = tuple(c >= DOW_ON for c in cov)
    if not any(active):
        return None, {}
    stray = sum(1 for x in days if not active[x.weekday()]) / len(days)
    if stray > STRAY_MAX:
        return None, {"stray": round(stray, 2)}
    if all(active) and min(cov) < DAILY_MIN:
        return None, {"daily_min": round(min(cov), 2)}
    return _classify_day_flags(active), {
        "cov": [round(c, 2) for c in cov], "stray": round(stray, 2)}


def survey(zip_path: str, config) -> list[str]:
    try:
        snap = load_snapshot(zip_path, config=config)
    except Exception as e:  # noqa: BLE001
        return [f"  (load 失敗: {e})"]
    cal = snap.table("calendar")
    flagged = set()
    if cal is not None and not cal.empty and (
        set(_CALENDAR_DAY_COLUMNS) <= set(cal.columns)
    ):
        for _, row in cal.iterrows():
            if any(str(row[c]).strip() == "1" for c in _CALENDAR_DAY_COLUMNS):
                flagged.add(str(row.get("service_id", "")))
    cd = snap.table("calendar_dates")
    if cd is None or cd.empty:
        return []
    added: dict[str, list[str]] = {}
    for sid, date, et in zip(cd["service_id"], cd["date"], cd["exception_type"]):
        if str(et).strip() == "1" and str(sid) not in flagged:
            added.setdefault(str(sid), []).append(str(date).strip())
    out = []
    for sid, dates in sorted(added.items()):
        cur = snap.day_types.get(sid)
        prop, info = dow_label(dates)
        if prop and prop != cur:
            out.append(f"  {sid}: {cur} → {prop} ({len(dates)}日, {info})")
    return out


def main() -> None:
    config = Config.load(None)
    roots = [
        "data/nemuro/*.zip",
        "data/daypattern_pairs/*/*.zip",
        "data/intl/*/*.zip",
        "data/nagoya/*.zip",
        "data/rinko/*.zip",
        "data/bus-vision-mie/*.zip",
        "data/kuwana_api/*.zip",
        "data/intl/lametro/*.zip",
        "data/daytype_survey/*.zip",
    ]
    seen = set()
    n_feeds = n_changed_feeds = n_changes = 0
    for pattern in roots:
        for z in sorted(glob.glob(pattern)):
            if z in seen:
                continue
            seen.add(z)
            n_feeds += 1
            rows = survey(z, config)
            if rows:
                n_changed_feeds += 1
                n_changes += len(rows)
                print(f"== {z}")
                for r in rows:
                    print(r)
    print(f"\n計: {n_feeds} zip 中 {n_changed_feeds} zip で計 {n_changes} service の"
          f"ラベルが変わる (DOW_ON={DOW_ON}, STRAY_MAX={STRAY_MAX})")


if __name__ == "__main__":
    main()
