"""I1: 国際検証データセットの実行記録 (docs/design/i18n.md)。

data/intl/{id}/old.zip, new.zip の各ペアに compare を実行し、完走/失敗・所要時間・
ピークメモリ・RawDiff/イベント数・explained_ratio・残差内訳を JSON で記録する。
フィードごとにサブプロセスで隔離 (国家規模フィードの OOM/暴走が全体を道連れに
しないため。タイムアウトは --timeout 秒)。

使い方:
  .venv.nosync/bin/python scripts/probe_intl_feeds.py            # 全ペア
  .venv.nosync/bin/python scripts/probe_intl_feeds.py trimet     # 指定のみ
結果: data/intl/results.json (追記でなく毎回上書き。台帳へは手で転記)
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "intl"


def run_one(feed_id: str) -> dict:
    """子プロセス側: 1ペアを実行して計測 JSON を stdout 最終行に出す。"""
    import faulthandler
    import logging

    logging.basicConfig(level=logging.WARNING)
    # ハング/超低速の診断用: 3分ごとにスタックを stderr へ (親が crash 時に tail を記録)
    faulthandler.dump_traceback_later(180, repeat=True)
    from gtfs_semantic_diff.config import Config
    from gtfs_semantic_diff.events import pipeline as pl
    from gtfs_semantic_diff.events.pipeline import compare_snapshots
    from gtfs_semantic_diff.load import load_snapshot

    # ステージ計測 (タイムアウトしても「どこまで進んだか」を親が回収できるよう
    # 都度 flush で stdout へ)。パイプラインの中身は変えない
    def timed(name, fn):
        def wrapped(*a, **k):
            t = time.time()
            r = fn(*a, **k)
            print(f"###MARK### {name}={round(time.time() - t, 1)}s", flush=True)
            return r
        return wrapped

    pl.enumerate_rawdiffs = timed("diff0", pl.enumerate_rawdiffs)
    pl.build_identity = timed("identity", pl.build_identity)
    pl.build_trip_delta = timed("tripdelta", pl.build_trip_delta)

    d = DATA_DIR / feed_id
    out: dict = {"feed": feed_id}
    t0 = time.time()
    config = Config.load()
    old = load_snapshot(d / "old.zip", config=config)
    new = load_snapshot(d / "new.zip", config=config)
    out["load_s"] = round(time.time() - t0, 1)
    out["old_files"] = sorted(old.table_names())
    out["stop_times_rows"] = [
        len(s.table("stop_times")) if s.table("stop_times") is not None else 0
        for s in (old, new)
    ]
    t1 = time.time()
    event_set, rawdiffs = compare_snapshots(old, new, config)
    out["compare_s"] = round(time.time() - t1, 1)
    acc = event_set.accounting
    out.update(
        rawdiffs=len(rawdiffs),
        events=len(event_set.events),
        explained_ratio=round(acc.explained_ratio, 4),
        residual_top=dict(sorted(acc.residual_breakdown_by_file.items(),
                                 key=lambda kv: -kv[1])[:6]),
        peak_rss_gb=round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2),
        total_s=round(time.time() - t0, 1),
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("feeds", nargs="*")
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--child", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.child:  # 子プロセスモード
        print("###RESULT### " + json.dumps(run_one(args.child), ensure_ascii=False))
        return

    feeds = args.feeds or sorted(
        p.name for p in DATA_DIR.iterdir()
        if (p / "old.zip").exists() and (p / "new.zip").exists())
    results = []
    for feed_id in feeds:
        print(f"== {feed_id} ==", flush=True)
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, __file__, "--child", feed_id],
                capture_output=True, text=True, timeout=args.timeout)
            line = next((ln for ln in proc.stdout.splitlines()
                         if ln.startswith("###RESULT### ")), None)
            marks = [ln.removeprefix("###MARK### ")
                     for ln in proc.stdout.splitlines()
                     if ln.startswith("###MARK### ")]
            if line:
                res = json.loads(line.removeprefix("###RESULT### "))
                res["stages"] = marks
            else:
                res = {"feed": feed_id, "error": "crashed",
                       "exit_code": proc.returncode,
                       "stderr_tail": proc.stderr[-500:],
                       "total_s": round(time.time() - t0, 1)}
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or b"")
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            marks = [ln.removeprefix("###MARK### ")
                     for ln in stdout.splitlines()
                     if ln.startswith("###MARK### ")]
            res = {"feed": feed_id, "error": f"timeout (>{args.timeout}s)",
                   "stages_completed": marks}
        results.append(res)
        print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)

    (DATA_DIR / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n書き出し: {DATA_DIR / 'results.json'}")


if __name__ == "__main__":
    main()
