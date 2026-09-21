"""Web (diff.gtfs.jp) にローカル zip ペアをアップロード投入し、完了まで待つ。

XL1/XL3 の規模実測 (docs/perf/XL1_lambda_limits.md) の再現手段。ブラウザの
入力 UI と同じ API を叩く: /api/uploads (presigned POST 発行) → S3 へ POST →
/api/jobs {type: "upload"} → /api/jobs/{id} をポーリング。

使い方:
  .venv.nosync/bin/python scripts/web_submit_upload.py data/intl/trimet/old.zip \
      data/intl/trimet/new.zip [--base https://diff.gtfs.jp] [--no-wait]

出力 (標準出力に 1 行 JSON): job_id / 最終 status / 所要秒 / result_url または
error。メモリ・時間の実測値は CloudWatch の worker REPORT 行で読む
(docs/perf/XL1_lambda_limits.md「測定方法」)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests

UA = "gtfs-semantic-diff-xl-measure/1.0"


def upload(base: str, old: Path, new: Path) -> dict:
    r = requests.post(f"{base}/api/uploads", headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    posts = r.json()["uploads"]
    keys = {}
    for side, path in (("old", old), ("new", new)):
        p = posts[side]
        with open(path, "rb") as f:
            t0 = time.time()
            s = requests.post(p["url"], data=p["fields"], files={"file": f}, timeout=600)
        if s.status_code not in (200, 201, 204):
            raise SystemExit(f"{side} upload failed: {s.status_code} {s.text[:200]}")
        print(f"  {side}: {path.name} ({path.stat().st_size / 1e6:.0f} MB) "
              f"uploaded in {time.time() - t0:.0f}s", file=sys.stderr)
        keys[f"{side}_key"] = p["key"]
    return keys


def submit(base: str, keys: dict, names: dict) -> tuple[int, dict]:
    r = requests.post(f"{base}/api/jobs", json={"type": "upload", **keys, **names},
                      headers={"User-Agent": UA}, timeout=60)
    return r.status_code, r.json()


def wait(base: str, status_url: str, interval: float = 10.0) -> dict:
    t0 = time.time()
    while True:
        r = requests.get(urllib.parse.urljoin(base, status_url),
                         headers={"User-Agent": UA}, timeout=30)
        j = r.json()
        st = j.get("status")
        if st in ("succeeded", "failed"):
            j["elapsed_s"] = round(time.time() - t0)
            return j
        print(f"  {st} … {time.time() - t0:.0f}s", file=sys.stderr)
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--base", default="https://diff.gtfs.jp")
    ap.add_argument("--name", default="", help="表示名 (old_name/new_name に同じ値)")
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args(argv)
    base = a.base.rstrip("/")
    print(f"upload → {base}", file=sys.stderr)
    keys = upload(base, a.old, a.new)
    names = {"old_name": a.name or a.old.name, "new_name": a.name or a.new.name}
    code, body = submit(base, keys, names)
    if code != 202:
        # XL2 ゲートで断られた場合もここ (400 + ja/en メッセージ)
        print(json.dumps({"submitted": False, "http": code, **body}, ensure_ascii=False))
        return 1
    out = {"submitted": True, "job_id": body.get("job_id"),
           "status_url": body.get("status_url")}
    print(f"  job {out['job_id']} queued", file=sys.stderr)
    if not a.no_wait:
        out.update(wait(base, body["status_url"]))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("status", "queued") != "failed" else 2


if __name__ == "__main__":
    sys.exit(main())
