"""EXP2 の12フィードペアの digest を一括生成する (RD4a 残 DoD 検証用、2026-08-19)。

各フィードの世代一覧を gtfs-data.jp から取り、告知の改正日を跨ぐペア
(new = 改正日以降で最初の世代、old = その直前の世代) を選んで
zip を取得し、L0 digest (md+json) を生成する。
CHI (地鉄)・NAGAI (永井) はローカル取得済み zip (シートと同一ペア) を使う。
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "exp2"
API = "https://api.gtfs-data.jp/v2"

# (label, org, feed, 改正日 YYYY-MM-DD)
TARGETS = [
    ("SUWA", "suwacity", "karinchanbas", "2026-04-01"),
    ("TSU", "tsucity", "communitybus", "2026-04-01"),
    ("TAKAOKA", "takaokacity", "koueibus", "2026-04-01"),
    ("KITA", "kitanagoyacity", "communitybus", "2026-07-27"),
    ("NAGANO", "naganocity", "shiei_noriaibus", "2026-04-01"),
    ("YUKI", "yukicity", "junkaibus", "2026-08-03"),
    ("NAKA", "nakatown", "nakatownbus", "2026-04-01"),
    ("MIYAMA", "miyamacity", "MiyamaCityCommunityBus", "2026-03-02"),
    ("MATSU", "matsusakacity", "communitybus", "2026-04-01"),
    ("KAWA", "fukuoka-kawasakitown", "KawasakiTownFureaiBus", "2025-10-01"),
]
LOCAL = [
    ("CHI", "data/chitetsu/old.zip", "data/chitetsu/new.zip"),
    ("NAGAI", "data/nagai/old.zip", "data/nagai/new.zip"),
]


def pick_pair(org: str, feed: str, target: str) -> tuple[dict, dict]:
    url = f"{API}/organizations/{org}/feeds/{feed}?max_prev=8"
    with urllib.request.urlopen(url) as r:
        body = json.load(r)["body"]
    gens = sorted(body["gtfs_files"], key=lambda g: g["from_date"])
    new = next((g for g in gens if g["from_date"] >= target), gens[-1])
    olds = [g for g in gens if g["from_date"] < new["from_date"]]
    if not olds:
        raise RuntimeError(f"{org}/{feed}: 旧世代が見つからない (target {target})")
    return olds[-1], new


def download(org: str, feed: str, uid: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    url = f"{API}/organizations/{org}/feeds/{feed}/files/feed.zip?uid={uid}"
    with urllib.request.urlopen(url) as r:
        dest.write_bytes(r.read())


def run_digest(label: str, old_zip: str, new_zip: str) -> None:
    cmd = [str(ROOT / ".venv.nosync/bin/gtfs-semantic-diff"), "compare",
           old_zip, new_zip,
           "--digest", str(OUT / f"{label}.digest.md"),
           "--digest-json", str(OUT / f"{label}.digest.json")]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if res.returncode != 0:
        print(f"[{label}] FAILED:\n{res.stdout[-500:]}\n{res.stderr[-500:]}",
              flush=True)
    else:
        print(f"[{label}] ok", flush=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for label, org, feed, target in TARGETS:
        try:
            old_g, new_g = pick_pair(org, feed, target)
            oz = OUT / f"{label}_old.zip"
            nz = OUT / f"{label}_new.zip"
            download(org, feed, old_g["gtfs_file_uid"], oz)
            download(org, feed, new_g["gtfs_file_uid"], nz)
            manifest[label] = {
                "org": org, "feed": feed, "target": target,
                "old": {"rid": old_g["rid"], "from": old_g["from_date"],
                        "uid": old_g["gtfs_file_uid"]},
                "new": {"rid": new_g["rid"], "from": new_g["from_date"],
                        "uid": new_g["gtfs_file_uid"]},
            }
            print(f"[{label}] {old_g['from_date']} ({old_g['rid']}) → "
                  f"{new_g['from_date']} ({new_g['rid']})", flush=True)
            run_digest(label, str(oz), str(nz))
        except Exception as e:  # noqa: BLE001 調査スクリプト
            print(f"[{label}] FAILED: {e}", flush=True)
    for label, oz, nz in LOCAL:
        manifest[label] = {"local": [oz, nz]}
        run_digest(label, str(ROOT / oz), str(ROOT / nz))
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", flush=True)
