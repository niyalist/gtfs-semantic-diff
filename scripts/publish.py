"""生成済み HTML レポートを配信基盤 (W3-0) へアップロードし公開 URL を表示する。

管理者用 (W3-1 でジョブ API ができるまでの公開手段 + 動作確認用)。
バケット名等は `cdk deploy --outputs-file outputs.json` が書いた
infra/outputs.json から読む。AWS 認証は aws CLI (プロファイル) に委ねる。

usage:
  .venv.nosync/bin/python scripts/publish.py data/v3_nagai.html \
      --id nagai-unyu__Nagaibus__prev_2__prev_1 --profile gtfs-semantic-diff

  --id 省略時はファイル名 (拡張子なし) を使う。公開先: https://{domain}/r/{id}.html
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

OUTPUTS = Path(__file__).resolve().parent.parent / "infra" / "outputs.json"
STACK = "GtfsSemdiffDelivery"


def aws(args: list[str], profile: str | None) -> None:
    cmd = ["aws", *args]
    if profile:
        cmd += ["--profile", profile]
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("html", type=Path, help="公開する自己完結 HTML")
    ap.add_argument("--id", dest="report_id", help="URL の ID (既定: ファイル名)")
    ap.add_argument("--profile", help="aws CLI プロファイル名")
    args = ap.parse_args()

    if not args.html.is_file():
        sys.exit(f"ファイルがありません: {args.html}")
    if not OUTPUTS.is_file():
        sys.exit(
            f"{OUTPUTS} がありません。先に infra/ で "
            "`npx aws-cdk deploy --outputs-file outputs.json` を実行してください。"
        )
    out = json.loads(OUTPUTS.read_text())[STACK]
    bucket, dist_id, domain = (
        out["BucketName"], out["DistributionId"], out["DistributionDomain"]
    )

    report_id = args.report_id or args.html.stem
    if not re.fullmatch(r"[A-Za-z0-9._~-]+(__[A-Za-z0-9._~-]+)*", report_id):
        sys.exit(f"ID に使えない文字が含まれています: {report_id}")
    key = f"r/{report_id}.html"

    aws(
        ["s3", "cp", str(args.html), f"s3://{bucket}/{key}",
         "--content-type", "text/html; charset=utf-8",
         "--cache-control", "public, max-age=300"],
        args.profile,
    )
    aws(
        ["cloudfront", "create-invalidation", "--distribution-id", dist_id,
         "--paths", f"/{key}", "--no-cli-pager"],
        args.profile,
    )
    print(f"\n公開 URL: https://{domain}/{key}")


if __name__ == "__main__":
    main()
