"""W3-1: ジョブ API と比較ワーカーの Lambda ハンドラ (設計: docs/design/web.md)。

同一コンテナイメージで CMD を変えて2関数として動く:
- handler.api    — HTTP API (CloudFront /api/* 経由)。ジョブ投入・状態照会・
                   gtfs-data.jp プロキシ (ブラウザの CORS 回避)・アップロード URL 発行
- handler.worker — 非同期起動される比較本体。compare → HTML → S3 r/ へ書き込み

コアは純関数のまま (設計原則3)。ここは薄い I/O 層に徹する。
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
import traceback
import urllib.parse
from pathlib import Path

import boto3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import os  # noqa: E402

RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET", "")
JOBS_TABLE = os.environ.get("JOBS_TABLE", "")
WORKER_FUNCTION = os.environ.get("WORKER_FUNCTION", "")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
JOB_TTL_DAYS = 30
MAX_PREV = 12

_ID_RE = re.compile(r"[A-Za-z0-9._-]+")

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
lam = boto3.client("lambda")


def _jobs_table():
    return ddb.Table(JOBS_TABLE)


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _bad(msg: str) -> dict:
    return _resp(400, {"error": msg})


def _safe_id(value: str) -> str:
    if not value or not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid id component: {value!r}")
    return value


# --- API ---


def api(event, context):  # noqa: ARG001 - Lambda signature
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "")
    qs = event.get("queryStringParameters") or {}
    try:
        if method == "GET" and path == "/api/gtfs/feeds":
            return _api_feeds(qs)
        if method == "GET" and path == "/api/gtfs/files":
            return _api_files(qs)
        if method == "POST" and path == "/api/uploads":
            return _api_uploads()
        if method == "POST" and path == "/api/jobs":
            return _api_submit(json.loads(event.get("body") or "{}"))
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9._-]+)", path)
        if method == "GET" and m:
            return _api_status(m.group(1))
        return _resp(404, {"error": "not found"})
    except ValueError as e:
        return _bad(str(e))
    except Exception:
        logger.exception("api error")
        return _resp(500, {"error": "internal error"})


def _api_feeds(qs: dict) -> dict:
    from gtfs_semantic_diff.config import Config
    from gtfs_semantic_diff.load import GtfsDataRepository

    repo = GtfsDataRepository(config=Config.load())
    pref = qs.get("pref")
    org = qs.get("org_id")
    if not pref and not org:
        return _bad("pref or org_id required")
    feeds = repo.list_feeds(org_id=org, pref=int(pref) if pref else None)
    return _resp(200, {
        "feeds": [
            {"org_id": f.org_id, "feed_id": f.feed_id,
             "name": f.name, "org_name": f.org_name}
            for f in feeds
        ]
    })


def _api_files(qs: dict) -> dict:
    from gtfs_semantic_diff.config import Config
    from gtfs_semantic_diff.load import GtfsDataRepository
    from gtfs_semantic_diff.load.repository import rid_order

    org = _safe_id(qs.get("org", ""))
    feed = _safe_id(qs.get("feed", ""))
    repo = GtfsDataRepository(config=Config.load())
    files = sorted(repo.get_feed_files(org, feed, max_prev=MAX_PREV),
                   key=lambda f: rid_order(f.rid))
    return _resp(200, {
        "files": [
            {"rid": f.rid, "from_date": f.from_date, "to_date": f.to_date,
             "memo": f.memo}
            for f in files
        ]
    })


def _api_uploads() -> dict:
    token = secrets.token_hex(8)
    posts = {}
    for side in ("old", "new"):
        key = f"uploads/{token}/{side}.zip"
        posts[side] = s3.generate_presigned_post(
            Bucket=RESULTS_BUCKET,
            Key=key,
            Conditions=[["content-length-range", 1, MAX_UPLOAD_BYTES]],
            ExpiresIn=900,
        )
        posts[side]["key"] = key
    return _resp(200, {"uploads": posts, "max_bytes": MAX_UPLOAD_BYTES})


def _api_submit(body: dict) -> dict:
    input_type = body.get("type")
    if input_type == "gtfs_data_jp":
        org = _safe_id(body.get("org", ""))
        feed = _safe_id(body.get("feed", ""))
        old_rid = _safe_id(body.get("old_rid", ""))
        new_rid = _safe_id(body.get("new_rid", ""))
        if old_rid == new_rid:
            return _bad("新旧に同じ世代が指定されています")
        job_id = f"{org}__{feed}__{old_rid}__{new_rid}"
        job_input = {"type": input_type, "org": org, "feed": feed,
                     "old_rid": old_rid, "new_rid": new_rid}
    elif input_type == "upload":
        old_key = body.get("old_key", "")
        new_key = body.get("new_key", "")
        if not (old_key.startswith("uploads/") and new_key.startswith("uploads/")):
            return _bad("invalid upload keys")
        job_id = f"anon-{secrets.token_hex(6)}"
        job_input = {"type": input_type, "old_key": old_key, "new_key": new_key}
    else:
        return _bad("type must be gtfs_data_jp or upload")

    now = int(time.time())
    _jobs_table().put_item(Item={
        "job_id": job_id,
        "status": "queued",
        "created_at": now,
        "expire_at": now + JOB_TTL_DAYS * 86400,
    })
    lam.invoke(
        FunctionName=WORKER_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps({"job_id": job_id, "input": job_input}).encode(),
    )
    return _resp(202, {"job_id": job_id,
                       "status_url": f"/api/jobs/{urllib.parse.quote(job_id)}"})


def _api_status(job_id: str) -> dict:
    item = _jobs_table().get_item(Key={"job_id": job_id}).get("Item")
    if not item:
        return _resp(404, {"error": "unknown job"})
    body = {"job_id": job_id, "status": item["status"]}
    if "result_url" in item:
        body["result_url"] = item["result_url"]
    if "error" in item:
        body["error"] = item["error"]
    return _resp(200, body)


# --- ワーカー ---


def _update(job_id: str, **attrs) -> None:
    expr = ", ".join(f"#k{i} = :v{i}" for i in range(len(attrs)))
    _jobs_table().update_item(
        Key={"job_id": job_id},
        UpdateExpression=f"SET {expr}",
        ExpressionAttributeNames={f"#k{i}": k for i, k in enumerate(attrs)},
        ExpressionAttributeValues={f":v{i}": v for i, v in enumerate(attrs.values())},
    )


def worker(event, context):  # noqa: ARG001 - Lambda signature
    job_id = event["job_id"]
    job_input = event["input"]
    _update(job_id, status="running")
    try:
        result_key = _run_compare(job_id, job_input)
        _update(job_id, status="succeeded", result_url=f"/{result_key}")
        logger.info("job %s succeeded: %s", job_id, result_key)
    except Exception as e:
        logger.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
        _update(job_id, status="failed", error=str(e)[:500])


def _run_compare(job_id: str, job_input: dict) -> str:
    from gtfs_semantic_diff.config import Config
    from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts
    from gtfs_semantic_diff.load import GtfsDataRepository, load_snapshot
    from gtfs_semantic_diff.report.bundle import build_bundle, render_html

    config = Config.load()
    if job_input["type"] == "gtfs_data_jp":
        repo = GtfsDataRepository(config=config)
        files = repo.get_feed_files(job_input["org"], job_input["feed"],
                                    max_prev=MAX_PREV)
        by_rid = {f.rid: f for f in files}
        for side in ("old_rid", "new_rid"):
            if job_input[side] not in by_rid:
                raise ValueError(f"世代 {job_input[side]} が見つかりません")
        fo, fn = by_rid[job_input["old_rid"]], by_rid[job_input["new_rid"]]
        old = load_snapshot(repo.download(fo).path, config=config,
                            meta=fo.snapshot_meta())
        new = load_snapshot(repo.download(fn).path, config=config,
                            meta=fn.snapshot_meta())
        result_key = f"r/{job_id}.html"
    else:
        paths = {}
        for side, key in (("old", job_input["old_key"]),
                          ("new", job_input["new_key"])):
            head = s3.head_object(Bucket=RESULTS_BUCKET, Key=key)
            if head["ContentLength"] > MAX_UPLOAD_BYTES:
                raise ValueError("アップロードサイズが上限を超えています")
            path = Path(f"/tmp/{side}.zip")
            s3.download_file(RESULTS_BUCKET, key, str(path))
            paths[side] = path
        old = load_snapshot(paths["old"], config=config)
        new = load_snapshot(paths["new"], config=config)
        result_key = f"r/anon/{job_id}.html"

    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    bundle = build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta)
    import gtfs_semantic_diff.report as report_pkg

    template = (Path(report_pkg.__file__).parent / "viewer_template.html").read_text(
        "utf-8"
    )
    html = render_html(bundle, template)
    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=result_key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl="public, max-age=300",
    )
    return result_key
