"""I1: 国際検証データセットの取得 (docs/design/i18n.md、台帳: docs/verification/intl_feeds.md)。

選定フィードの世代ペア (old/new) を data/intl/{id}/ にダウンロードする。
zip は再配布しない — このスクリプトと下の REGISTRY (URL・版の恒久固定) が
再現手段そのもの。Wayback Machine の URL は `id_` 付き (オリジナルバイト列)。

使い方:
  .venv.nosync/bin/python scripts/fetch_intl_feeds.py           # 全件
  .venv.nosync/bin/python scripts/fetch_intl_feeds.py trimet mbta  # 指定のみ
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "intl"
UA = "gtfs-semantic-diff-i18n-verification/1.0 (research; github.com/niyalist/gtfs-semantic-diff)"


def wb(timestamp: str, url: str) -> str:
    """Wayback Machine のオリジナルバイト列 URL。"""
    return f"https://web.archive.org/web/{timestamp}id_/{url}"


# 選定理由・特徴・ライセンスの台帳は docs/verification/intl_feeds.md (本 REGISTRY と同期)
REGISTRY: dict[str, dict] = {
    "trimet": {  # 歴史枠 (GTFS 発祥) + 模範実装
        "old": wb("20251204232706", "https://developer.trimet.org/schedule/gtfs.zip"),
        "new": wb("20260603051412", "https://developer.trimet.org/schedule/gtfs.zip"),
    },
    "mbta": {  # 歴史枠 + 多モード (地下鉄/CR/フェリー) + Fares v2 (公式アーカイブ)
        "old": "https://cdn.mbtace.com/archive/20251127.zip",  # Winter 2026 開始
        "new": "https://cdn.mbtace.com/archive/20260527.zip",  # Summer 2026 開始
    },
    "stm": {  # 歴史枠 + 仏語 (非 ASCII)
        "old": wb("20250613151423",
                  "https://www.stm.info/sites/default/files/gtfs/gtfs_stm.zip"),
        "new": wb("20260603051412",
                  "https://www.stm.info/sites/default/files/gtfs/gtfs_stm.zip"),
    },
    "rome": {  # frequencies.txt の代表格 + 伊語
        "old": wb("20250406113546",
                  "https://romamobilita.it/sites/default/files/rome_static_gtfs.zip"),
        "new": wb("20251014102853",
                  "https://romamobilita.it/sites/default/files/rome_static_gtfs.zip"),
    },
    "swiss": {  # 国家規模 (中) + 多モード鉄道 (公式の日付付き版)
        "old": "https://data.opentransportdata.swiss/dataset/3d2c18f9-9ef1-463f-a249-5c67604efd74/resource/0d67ae64-0364-49ae-8c24-b58d331fe969/download/gtfs_fp2026_20251220.zip",
        "new": "https://data.opentransportdata.swiss/dataset/3d2c18f9-9ef1-463f-a249-5c67604efd74/resource/0e706449-d94f-4f38-9f81-b97ca2d9f04c/download/gtfs_fp2026_20260606.zip",
    },
    "ovapi_nl": {  # calendar_dates 主体 + 国家規模 (大・ストレステスト)
        "old": "http://gtfs.ovapi.nl/nl/archive/NL-20260101.gtfs.zip",
        "new": "http://gtfs.ovapi.nl/nl/NL-20260711.gtfs.zip",
    },
}


def fetch(feed_id: str, side: str, url: str) -> None:
    dest = DATA_DIR / feed_id / f"{side}.zip"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  {feed_id}/{side}: キャッシュ済み ({dest.stat().st_size/1e6:.0f} MB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  {feed_id}/{side}: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    print(f"  {feed_id}/{side}: 完了 ({dest.stat().st_size/1e6:.0f} MB)")


def main() -> None:
    targets = sys.argv[1:] or list(REGISTRY)
    for feed_id in targets:
        entry = REGISTRY[feed_id]
        print(f"== {feed_id} ==")
        for side in ("old", "new"):
            try:
                fetch(feed_id, side, entry[side])
            except Exception as e:  # 続行 (台帳に記録するため全件試す)
                print(f"  {feed_id}/{side}: 取得失敗 — {e}")


if __name__ == "__main__":
    main()
