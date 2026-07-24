"""運行日パターン調査 (SD5/SD6 検討用の検証データセット構築)。

GTFS zip の calendar / calendar_dates / feed_info だけを読み、運行日の
表現パターンを機械分類する。設計議論: docs/verification/day_pattern_survey.md。

使い方:
  # ローカル zip 群
  .venv.nosync/bin/python scripts/survey_day_patterns.py local A.zip B.zip ...
  # gtfs-data.jp 全フィード走査 (current 世代のみ。結果は data/daytype_survey/)
  .venv.nosync/bin/python scripts/survey_day_patterns.py crawl [--limit N]

分類タグ:
  dow_odd          変則曜日フラグ (月水金など、標準6種以外)
  mixed_expiry     service 毎に有効期限がバラバラ (寄せ集め度: 終端の散らばり日数)
  cd_only          calendar 行なし・calendar_dates のみの service
  holiday_cd       cd_only かつ追加日 1〜5 日 (祝日専用の素朴型)
  holiday_flagged  フラグあり + 削除で希釈され実効 ≤5 日 (PRT 型)
  seasonal_split   同一フラグで期間が複数に分割 (STM 型・季節分割候補)
  swap_dates       同じ日付で type2 (運休) と type1 (代替運行) が対になる
                   (日本の祝日振替の標準形)
  school_kw        service_id に 学/校/スクール/休業 等 (学校日ダイヤ候補)
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import re
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "daytype_survey"
API = "https://api.gtfs-data.jp/v2"
STANDARD_FLAGS = {
    "1111100", "1111110", "0000011", "0000010", "0000001", "1111111", "0000000",
}
SCHOOL_RE = re.compile(r"学|校|スクール|休業|夏|冬|春")
MAX_ZIP_BYTES = 40 * 1024 * 1024


def _parse(d: str) -> datetime.date | None:
    d = (d or "").strip()
    if len(d) != 8 or not d.isdigit():
        return None
    try:
        return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    except ValueError:
        return None


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    cands = [n for n in zf.namelist()
             if n.split("/")[-1].lower() == name and not n.startswith("__MACOSX")]
    if not cands:
        return []
    with zf.open(sorted(cands, key=len)[0]) as f:
        text = io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace")
        return list(csv.DictReader(text))


def analyze_zip(path_or_bytes) -> dict:
    """calendar 系だけを読んで分類タグとメトリクスを返す。"""
    zf = zipfile.ZipFile(path_or_bytes)
    cal = _read_csv(zf, "calendar.txt")
    cd = _read_csv(zf, "calendar_dates.txt")
    fi = _read_csv(zf, "feed_info.txt")

    added: dict[str, set[str]] = defaultdict(set)
    removed: dict[str, set[str]] = defaultdict(set)
    for r in cd:
        s = (r.get("service_id") or "").strip()
        t = (r.get("exception_type") or "").strip()
        d = (r.get("date") or "").strip()
        (added if t == "1" else removed)[s].add(d)

    cols = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]
    metrics: dict = {
        "n_services_cal": len(cal), "n_cd_rows": len(cd),
        "flags_odd": [], "holiday_flagged": [], "seasonal_groups": [],
    }
    ranges: list[tuple[datetime.date, datetime.date]] = []
    by_flags: dict[str, list[tuple[datetime.date, datetime.date, str]]] = (
        defaultdict(list))
    for r in cal:
        sid = (r.get("service_id") or "").strip()
        flags = "".join("1" if (r.get(c) or "").strip() == "1" else "0"
                        for c in cols)
        start, end = _parse(r.get("start_date")), _parse(r.get("end_date"))
        if flags not in STANDARD_FLAGS:
            metrics["flags_odd"].append((sid, flags))
        if start and end and end >= start:
            ranges.append((start, end))
            by_flags[flags].append((start, end, sid))
            # フラグ該当日と実効日 (PRT 型の判定)
            flag_days = effective = 0
            if (end - start).days <= 800:
                d = start
                one = datetime.timedelta(days=1)
                while d <= end:
                    if flags[d.weekday()] == "1":
                        flag_days += 1
                        if d.strftime("%Y%m%d") not in removed.get(sid, ()):
                            effective += 1
                    d += one
                effective += len(added.get(sid, set()))
                if flag_days >= 8 and effective <= 5:
                    metrics["holiday_flagged"].append(
                        (sid, flags, flag_days, effective))
    # 期限の散らばり
    ends = sorted({e for _, e in ranges})
    metrics["distinct_ends"] = len(ends)
    metrics["end_spread_days"] = (ends[-1] - ends[0]).days if len(ends) > 1 else 0
    # 季節分割候補: 同一フラグの期間が重ならず2つ以上
    for flags, rs in by_flags.items():
        if flags == "0000000" or len(rs) < 2:
            continue
        rs2 = sorted(rs)
        if all(rs2[i][1] < rs2[i + 1][0] for i in range(len(rs2) - 1)):
            metrics["seasonal_groups"].append(
                (flags, [(s.isoformat(), e.isoformat(), sid)
                         for s, e, sid in rs2]))
    # calendar_dates のみの service
    cal_ids = {(r.get("service_id") or "").strip() for r in cal}
    cd_ids = set(added) | set(removed)
    cd_only = sorted(cd_ids - cal_ids)
    metrics["cd_only"] = len(cd_only)
    metrics["holiday_cd"] = [
        s for s in cd_only if 1 <= len(added.get(s, set())) <= 5]
    # 振替 (同日に type2 と type1)
    dates2 = {d for s in removed for d in removed[s]}
    dates1 = {d for s in added for d in added[s]}
    metrics["swap_dates"] = len(dates1 & dates2)
    metrics["school_kw"] = sorted(
        {s for s in (cal_ids | cd_ids) if SCHOOL_RE.search(s)})[:8]
    metrics["feed_info"] = fi[0] if fi else {}

    tags = []
    if metrics["flags_odd"]:
        tags.append("dow_odd")
    if metrics["distinct_ends"] >= 3 and metrics["end_spread_days"] >= 45:
        tags.append("mixed_expiry")
    if metrics["cd_only"] >= 1:
        tags.append("cd_only")
    if metrics["holiday_cd"]:
        tags.append("holiday_cd")
    if metrics["holiday_flagged"]:
        tags.append("holiday_flagged")
    if metrics["seasonal_groups"]:
        tags.append("seasonal_split")
    if metrics["swap_dates"] >= 3:
        tags.append("swap_dates")
    if metrics["school_kw"]:
        tags.append("school_kw")
    metrics["tags"] = tags
    return metrics


def run_local(paths: list[str]) -> None:
    for p in paths:
        m = analyze_zip(p)
        keep = {k: v for k, v in m.items()
                if k in ("tags", "n_services_cal", "n_cd_rows", "cd_only",
                         "distinct_ends", "end_spread_days", "swap_dates")}
        print(f"== {Path(p).name}: {keep}")
        for k in ("flags_odd", "holiday_flagged", "seasonal_groups",
                  "holiday_cd", "school_kw"):
            if m[k]:
                print(f"   {k}: {m[k][:6]}")


def run_crawl(limit: int | None) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    feeds = []
    for pref in range(1, 48):
        r = requests.get(f"{API}/feeds", params={"pref": pref}, timeout=30)
        r.raise_for_status()
        feeds.extend(r.json().get("body") or [])
        time.sleep(0.2)
    seen = set()
    targets = []
    for f in feeds:
        key = (f["organization_id"], f["feed_id"])
        if key not in seen:
            seen.add(key)
            targets.append(f)
    print(f"フィード {len(targets)} 件 (重複除去後)")
    if limit:
        targets = targets[:limit]

    results = []
    for i, f in enumerate(targets):
        org, fid = f["organization_id"], f["feed_id"]
        out = OUT_DIR / f"{org}__{fid}.json"
        if out.exists():
            results.append(json.loads(out.read_text(encoding="utf-8")))
            continue
        rec = {"org": org, "feed": fid, "name": f.get("feed_name"),
               "pref": f.get("feed_pref_id"), "license": f.get("feed_license")}
        try:
            d = requests.get(f"{API}/organizations/{org}/feeds/{fid}",
                             params={"max_prev": 0}, timeout=30).json()["body"]
            cur = next((g for g in d.get("gtfs_files") or []
                        if g["rid"] == "current"), None)
            if cur is None:
                rec["error"] = "no current"
            else:
                z = requests.get(cur["gtfs_url"], timeout=120)
                z.raise_for_status()
                if len(z.content) > MAX_ZIP_BYTES:
                    rec["error"] = f"too large ({len(z.content)} bytes)"
                else:
                    rec["zip_bytes"] = len(z.content)
                    rec["from_date"] = cur.get("from_date")
                    rec["to_date"] = cur.get("to_date")
                    m = analyze_zip(io.BytesIO(z.content))
                    # JSON 化できる形に間引く
                    m["flags_odd"] = m["flags_odd"][:10]
                    m["holiday_flagged"] = m["holiday_flagged"][:10]
                    m["seasonal_groups"] = m["seasonal_groups"][:5]
                    m["holiday_cd"] = m["holiday_cd"][:10]
                    rec.update(m)
        except Exception as e:  # noqa: BLE001 — 調査スクリプト: 個別失敗は記録して続行
            rec["error"] = f"{type(e).__name__}: {e}"
        out.write_text(json.dumps(rec, ensure_ascii=False, default=str),
                       encoding="utf-8")
        results.append(rec)
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(targets)} 済", flush=True)
        time.sleep(0.3)

    summary = defaultdict(list)
    for r in results:
        for t in r.get("tags", []):
            summary[t].append(f"{r['org']}/{r['feed']}")
    (OUT_DIR / "_summary.json").write_text(
        json.dumps({k: v for k, v in sorted(summary.items())},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("タグ別件数:", {k: len(v) for k, v in sorted(summary.items())})
    print(f"書き出し: {OUT_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_local = sub.add_parser("local")
    p_local.add_argument("zips", nargs="+")
    p_crawl = sub.add_parser("crawl")
    p_crawl.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    if args.cmd == "local":
        run_local(args.zips)
    else:
        run_crawl(args.limit)


if __name__ == "__main__":
    main()
