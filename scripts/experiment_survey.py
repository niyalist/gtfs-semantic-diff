"""EXP1: コーパス横断の被覆率・性能計測 (論文評価章用)。

数百フィード規模で compare を実行し、フィードペアごとに1行の CSV を出力する。
計測は読み取り専用 — コアには一切手を入れず、フェーズ時間は pipeline
モジュール名前空間の関数を計時ラッパで包んで測る (出力はバイト不変)。

使い方 (リポジトリルートで、Mac の venv から):

  # パイロット: 検証フィード群のみ
  .venv.nosync/bin/python scripts/experiment_survey.py --pilot \
      --out data/experiments/pilot.csv

  # 本計測: gtfs-data.jp の全フィード (夜間実行想定)
  .venv.nosync/bin/python scripts/experiment_survey.py --all \
      --out data/experiments/corpus.csv

  # 決定性チェック付き (各ペアを2回実行しイベント JSON のハッシュ比較)
  ... --repeat 2

  # ローカル zip ペア (国際データセット等): old.zip new.zip の組を列挙
  ... --local data/intl/mbta/old.zip data/intl/mbta/new.zip --label mbta

出力 CSV の列は SCHEMA を参照。失敗したペアも error 列に記録して1行残す
(頑健性のデータ)。結果と分析は docs/verification/EXP1_corpus.md に記録する。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from gtfs_semantic_diff.config import Config  # noqa: E402
from gtfs_semantic_diff.load import GtfsDataRepository, load_snapshot  # noqa: E402
from gtfs_semantic_diff.load.repository import RepositoryError, rid_order  # noqa: E402
from gtfs_semantic_diff.events import pipeline  # noqa: E402
from gtfs_semantic_diff.identity.builder import blocking_family_maps  # noqa: E402

# パイロット (検証フィードの API 系列)
PILOT_FEEDS = [
    ("nagai-unyu", "Nagaibus"),
    ("chitetsu", "chitetsubus"),
    ("toyama-asahitown", "asahimachibus"),
]

SCHEMA = [
    # 識別
    "label", "org_id", "feed_id", "old_rid", "new_rid",
    "old_from_date", "new_from_date",
    # 入力規模
    "old_zip_bytes", "new_zip_bytes",
    "rows_stops", "rows_routes", "rows_trips", "rows_stop_times",
    "rows_shapes", "rows_calendar_dates", "rows_fare_rules",
    "n_stop_clusters", "n_families", "n_route_groups", "n_patterns",
    "n_day_types", "n_trips_old", "n_trips_new",
    "block_max", "block_sq_sum",
    # 出力
    "rawdiff_total", "rd_row_added", "rd_row_removed", "rd_field_changed",
    "rd_other", "bulk_used",
    "n_events", "explained", "explained_ratio",
    "residual_count", "residual_by_file",
    "events_by_type",
    "trip_exact", "trip_churn", "trip_modified", "trip_removed", "trip_added",
    # 時間 (秒)
    "t_load", "t_diff0", "t_identity", "t_tripdelta", "t_rules", "t_total",
    # 検証
    "det_hash", "det_match", "error",
]


class PhaseTimer:
    """pipeline モジュールの名前を計時ラッパで包む (出力不変・読み取り専用)。"""

    def __init__(self) -> None:
        self.acc: dict[str, float] = {}
        self._orig: dict[str, object] = {}

    def _wrap(self, name: str, phase: str):
        orig = getattr(pipeline, name)
        self._orig[name] = orig

        def timed(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return orig(*args, **kwargs)
            finally:
                self.acc[phase] = self.acc.get(phase, 0.0) + (
                    time.perf_counter() - t0
                )

        setattr(pipeline, name, timed)

    def __enter__(self) -> "PhaseTimer":
        self._wrap("enumerate_rawdiffs", "diff0")
        self._wrap("build_identity", "identity")
        self._wrap("collect_trips", "tripdelta")
        self._wrap("build_trip_delta", "tripdelta")
        return self

    def __exit__(self, *exc) -> None:
        for name, orig in self._orig.items():
            setattr(pipeline, name, orig)


def event_set_hash(event_set) -> str:
    """決定性チェック用のハッシュ (実行時刻 generated_at を除外)。"""
    d = event_set.to_dict()
    d.pop("generated_at", None)
    blob = json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def measure_pair(
    label: str,
    old_path: Path,
    new_path: Path,
    config: Config,
    meta: dict | None = None,
    repeat: int = 1,
) -> dict:
    row: dict = {k: "" for k in SCHEMA}
    row["label"] = label
    row.update(meta or {})
    row["old_zip_bytes"] = old_path.stat().st_size
    row["new_zip_bytes"] = new_path.stat().st_size

    t0 = time.perf_counter()
    old = load_snapshot(old_path, config)
    new = load_snapshot(new_path, config)
    row["t_load"] = round(time.perf_counter() - t0, 3)

    for table, col in [
        ("stops", "rows_stops"), ("routes", "rows_routes"),
        ("trips", "rows_trips"), ("stop_times", "rows_stop_times"),
        ("shapes", "rows_shapes"), ("calendar_dates", "rows_calendar_dates"),
        ("fare_rules", "rows_fare_rules"),
    ]:
        o, n = old.table(table), new.table(table)
        row[col] = (0 if o is None else len(o)) + (0 if n is None else len(n))

    hashes = []
    for i in range(max(1, repeat)):
        timer = PhaseTimer()
        t1 = time.perf_counter()
        with timer:
            event_set, rawdiffs, identity, delta = (
                pipeline.compare_snapshots_with_artifacts(old, new, config)
            )
        total = time.perf_counter() - t1
        hashes.append(event_set_hash(event_set))
        if i == 0:  # 計測値は初回のみ記録
            row["t_total"] = round(total, 3)
            row["t_diff0"] = round(timer.acc.get("diff0", 0.0), 3)
            row["t_identity"] = round(timer.acc.get("identity", 0.0), 3)
            row["t_tripdelta"] = round(timer.acc.get("tripdelta", 0.0), 3)
            row["t_rules"] = round(
                total
                - timer.acc.get("diff0", 0.0)
                - timer.acc.get("identity", 0.0)
                - timer.acc.get("tripdelta", 0.0),
                3,
            )
            _fill_outputs(row, event_set, rawdiffs, identity, delta, old, new)
    row["det_hash"] = hashes[0]
    row["det_match"] = int(len(set(hashes)) == 1)
    return row


def _fill_outputs(row, event_set, rawdiffs, identity, delta, old, new) -> None:
    kinds = Counter(d.kind for d in rawdiffs.diffs)
    row["rawdiff_total"] = len(rawdiffs)
    row["rd_row_added"] = kinds.get("row_added", 0)
    row["rd_row_removed"] = kinds.get("row_removed", 0)
    row["rd_field_changed"] = kinds.get("field_changed", 0)
    row["rd_other"] = len(rawdiffs) - sum(
        kinds.get(k, 0) for k in ("row_added", "row_removed", "field_changed")
    )
    row["bulk_used"] = int(any(k.endswith("_bulk") for k in kinds))

    acc = event_set.accounting
    events = event_set.events
    residual = [e for e in events if e.type == "UNEXPLAINED_RESIDUAL"]
    row["n_events"] = len(events)
    row["explained"] = acc.explained
    row["explained_ratio"] = round(acc.explained_ratio, 6)
    row["residual_count"] = sum(len(e.evidence) for e in residual)
    row["residual_by_file"] = json.dumps(
        acc.residual_breakdown_by_file, ensure_ascii=False, sort_keys=True,
    )
    row["events_by_type"] = json.dumps(
        dict(sorted(Counter(e.type for e in events).items())), ensure_ascii=False
    )

    row["n_stop_clusters"] = len(identity.old_stop_clusters) + len(
        identity.new_stop_clusters
    )
    row["n_families"] = len(identity.old_families) + len(identity.new_families)
    row["n_route_groups"] = _route_group_count(identity)
    row["n_patterns"] = _pattern_count(identity)
    row["n_day_types"] = len(set(old.day_types.values()) | set(new.day_types.values()))

    row["n_trips_old"] = len(delta.old_trips)
    row["n_trips_new"] = len(delta.new_trips)
    row["trip_exact"] = len(delta.exact_pairs)
    row["trip_churn"] = len(delta.churn_pairs)
    row["trip_modified"] = len(delta.modified)
    row["trip_removed"] = len(delta.removed)
    row["trip_added"] = len(delta.added)

    # ブロック規模 (性能仮説 Σblock² の説明変数)
    old_block, new_block = blocking_family_maps(identity)
    blocks: Counter = Counter()
    for t in delta.old_trips.values():
        blocks[(old_block.get(t.family, t.family), t.day_type)] += 1
    for t in delta.new_trips.values():
        blocks[(new_block.get(t.family, t.family), t.day_type)] += 1
    sizes = list(blocks.values()) or [0]
    row["block_max"] = max(sizes)
    row["block_sq_sum"] = sum(s * s for s in sizes)


def _route_group_count(identity) -> int:
    return len(identity.old_groups) + len(identity.new_groups)


def _pattern_count(identity) -> int:
    return len(identity.old_pattern_clusters) + len(identity.new_pattern_clusters)


def iter_api_pairs(repo: GtfsDataRepository, feeds, limit: int | None):
    count = 0
    for org_id, feed_id in feeds:
        if limit is not None and count >= limit:
            return
        try:
            files = repo.get_feed_files(org_id, feed_id, max_prev=2)
        except (RepositoryError, Exception) as exc:  # noqa: BLE001
            yield org_id, feed_id, None, None, f"list: {exc}"
            count += 1
            continue
        files_sorted = sorted(files, key=lambda f: rid_order(f.rid))
        if len(files_sorted) < 2:
            yield org_id, feed_id, None, None, "世代が2つ未満"
            count += 1
            continue
        new_info, old_info = files_sorted[0], files_sorted[1]
        yield org_id, feed_id, old_info, new_info, None
        count += 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pilot", action="store_true", help="検証フィード群のみ")
    ap.add_argument("--all", action="store_true", help="gtfs-data.jp 全フィード")
    ap.add_argument("--limit", type=int, default=None, help="フィード数上限")
    ap.add_argument("--local", nargs=2, action="append", metavar=("OLD", "NEW"),
                    default=[], help="ローカル zip ペア (複数指定可)")
    ap.add_argument("--label", action="append", default=[],
                    help="--local ペアのラベル (指定順)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="2 以上で決定性チェック (同一ペアを複数回実行)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    config = Config.load()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():  # 再開: 既存行はスキップ
        with args.out.open() as f:
            done = {(r["org_id"], r["feed_id"], r["label"]) for r in csv.DictReader(f)}
    mode = "a" if done else "w"
    out_f = args.out.open(mode, newline="")
    writer = csv.DictWriter(out_f, fieldnames=SCHEMA)
    if mode == "w":
        writer.writeheader()

    def emit(row: dict) -> None:
        writer.writerow(row)
        out_f.flush()
        status = row["error"] or (
            f"ratio={row['explained_ratio']} total={row['t_total']}s"
        )
        print(f"[{row['label'] or row['org_id']+'/'+row['feed_id']}] {status}")

    # ローカルペア
    for i, (old_p, new_p) in enumerate(args.local):
        label = args.label[i] if i < len(args.label) else Path(old_p).parent.name
        if ("", "", label) in done:
            continue
        try:
            emit(measure_pair(label, Path(old_p), Path(new_p), config,
                              repeat=args.repeat))
        except Exception:  # noqa: BLE001
            row = {k: "" for k in SCHEMA}
            row["label"] = label
            row["error"] = traceback.format_exc(limit=1).strip().splitlines()[-1]
            emit(row)

    # API フィード
    if args.pilot or args.all:
        repo = GtfsDataRepository(config)
        if args.pilot:
            feeds = PILOT_FEEDS
        else:
            feeds = [(f.org_id, f.feed_id) for f in repo.list_feeds()]
        for org_id, feed_id, old_info, new_info, err in iter_api_pairs(
            repo, feeds, args.limit
        ):
            if (org_id, feed_id, "") in done:
                continue
            row = {k: "" for k in SCHEMA}
            row["org_id"], row["feed_id"] = org_id, feed_id
            if err:
                row["error"] = err
                emit(row)
                continue
            try:
                old_f = repo.download(old_info)
                new_f = repo.download(new_info)
                meta = {
                    "org_id": org_id, "feed_id": feed_id,
                    "old_rid": old_info.rid, "new_rid": new_info.rid,
                    "old_from_date": old_info.from_date,
                    "new_from_date": new_info.from_date,
                }
                emit(measure_pair("", old_f.path, new_f.path, config,
                                  meta=meta, repeat=args.repeat))
            except Exception:  # noqa: BLE001
                row["error"] = traceback.format_exc(limit=1).strip().splitlines()[-1]
                emit(row)

    out_f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
