"""W3-1/W3-2a: ジョブ API と比較ワーカーの Lambda ハンドラ (設計: docs/design/web.md)。

同一コンテナイメージで CMD を変えて2関数として動く:
- handler.api    — HTTP API (CloudFront /api/* 経由)。ジョブ投入・状態照会・
                   gtfs-data.jp プロキシ (ブラウザの CORS 回避)・アップロード URL 発行
- handler.worker — 非同期起動される比較本体。compare → HTML → S3 r/ へ書き込み

W3-2a (正準 URL と版管理、純ロジックは versioning.py):
- リポジトリ由来ジョブは世代恒久 UUID (gtfs_file_uid) ベースの正準キー。
  同一世代ペアは誰が実行しても同一 URL (実質公開・キャッシュとして機能)
- 結果は不変: r/{pair}/v/{版}.html に追記、入口 r/{pair}.html は最新版のコピー、
  index.json が版台帳。再生成は lazy (投入時にツール版が古いときだけ)
- アップロード由来は従来どおり実行ごとのランダム URL (限定公開・30日削除)

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
import versioning

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import os  # noqa: E402

RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET", "")
JOBS_TABLE = os.environ.get("JOBS_TABLE", "")
WORKER_FUNCTION = os.environ.get("WORKER_FUNCTION", "")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
JOB_TTL_DAYS = 30
MAX_PREV = 12  # 入力 UI に見せる世代数
# uid → 世代の解決に使う遡り数。UI の選択肢 (MAX_PREV) より深いのは、
# 過去に生成したペアの再比較時に世代が古くなっていても見つけるため
MAX_PREV_LOOKUP = 120

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


def _tool_version() -> str:
    import importlib.metadata

    try:
        return importlib.metadata.version("gtfs-semantic-diff")
    except importlib.metadata.PackageNotFoundError:
        return "0"


def _get_index(pair: str) -> dict | None:
    """版台帳 index.json を読む。未生成なら None。"""
    try:
        obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=versioning.index_key(pair))
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


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
            {"uid": f.uid, "rid": f.rid, "from_date": f.from_date,
             "to_date": f.to_date, "memo": f.memo}
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


def _resolve_uids(org: str, feed: str, old_rid: str, new_rid: str) -> tuple[str, str]:
    """旧クライアント互換: rid 指定を uid に解決する (rid は世代進行でずれるため
    正準キーには使わない)。"""
    from gtfs_semantic_diff.config import Config
    from gtfs_semantic_diff.load import GtfsDataRepository

    repo = GtfsDataRepository(config=Config.load())
    by_rid = {f.rid: f for f in repo.get_feed_files(org, feed, max_prev=MAX_PREV)}
    uids = []
    for rid in (old_rid, new_rid):
        info = by_rid.get(rid)
        if info is None or not info.uid:
            raise ValueError(f"世代 {rid} が見つかりません")
        uids.append(info.uid)
    return uids[0], uids[1]


def _api_submit(body: dict) -> dict:
    input_type = body.get("type")
    if input_type == "gtfs_data_jp":
        org = _safe_id(body.get("org", ""))
        feed = _safe_id(body.get("feed", ""))
        old_uid = body.get("old_uid", "")
        new_uid = body.get("new_uid", "")
        if not (old_uid and new_uid):
            old_uid, new_uid = _resolve_uids(
                org, feed,
                _safe_id(body.get("old_rid", "")), _safe_id(body.get("new_rid", "")),
            )
        old_uid = versioning.safe_uid(old_uid)
        new_uid = versioning.safe_uid(new_uid)
        if old_uid == new_uid:
            return _bad("新旧に同じ世代が指定されています")
        job_id = versioning.pair_id(org, feed, old_uid, new_uid)
        job_input = {"type": input_type, "org": org, "feed": feed,
                     "old_uid": old_uid, "new_uid": new_uid}
        status_url = f"/api/jobs/{urllib.parse.quote(job_id)}"
        now = int(time.time())
        # lazy 再生成: 保存済み最新版が現行ツール版なら計算せず即返す。
        # 版が古ければ新版を追記する (既存版は不変のまま残る)
        idx = _get_index(job_id)
        if idx and versioning.latest_version(idx) == _tool_version():
            result_url = f"/{versioning.entry_key(job_id)}"
            _jobs_table().put_item(Item={
                "job_id": job_id, "status": "succeeded",
                "result_url": result_url,
                "created_at": now, "expire_at": now + JOB_TTL_DAYS * 86400,
            })
            return _resp(202, {"job_id": job_id, "status_url": status_url,
                               "status": "succeeded", "result_url": result_url})
        # 同一ペアが計算中なら重複起動しない (ポーリング先だけ返す)
        existing = _jobs_table().get_item(Key={"job_id": job_id}).get("Item")
        if existing and existing.get("status") in ("queued", "running"):
            since = int(existing.get("running_since")
                        or existing.get("created_at") or 0)
            if since and time.time() - since < WORKER_MAX_SECONDS:
                return _resp(202, {"job_id": job_id, "status_url": status_url})
    elif input_type == "upload":
        old_key = body.get("old_key", "")
        new_key = body.get("new_key", "")
        if not (old_key.startswith("uploads/") and new_key.startswith("uploads/")):
            return _bad("invalid upload keys")
        job_id = f"anon-{secrets.token_hex(6)}"
        job_input = {"type": input_type, "old_key": old_key, "new_key": new_key}
        status_url = f"/api/jobs/{urllib.parse.quote(job_id)}"
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
    return _resp(202, {"job_id": job_id, "status_url": status_url})


WORKER_MAX_SECONDS = 16 * 60  # worker Lambda の timeout (15分) + 余裕


def _api_status(job_id: str) -> dict:
    item = _jobs_table().get_item(Key={"job_id": job_id}).get("Item")
    if not item:
        return _resp(404, {"error": "unknown job"})
    status = item["status"]
    # worker が Lambda タイムアウト/OOM で死ぬと running のまま残る
    # (例外ハンドラは走れない)。経過時間で失敗と判定してポーリングを止める
    if status == "running":
        since = int(item.get("running_since") or item.get("created_at") or 0)
        if since and time.time() - since > WORKER_MAX_SECONDS:
            status = "failed"
            _update(job_id, status="failed",
                    error="処理が制限時間 (15分) を超えました")
    body = {"job_id": job_id, "status": status}
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
    _update(job_id, status="running", running_since=int(time.time()))
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
    pair_feed_info = None
    if job_input["type"] == "gtfs_data_jp":
        repo = GtfsDataRepository(config=config)
        files = repo.get_feed_files(job_input["org"], job_input["feed"],
                                    max_prev=MAX_PREV_LOOKUP)
        by_uid = {f.uid: f for f in files}
        for side in ("old_uid", "new_uid"):
            if job_input[side] not in by_uid:
                raise ValueError(
                    f"世代 (uid={job_input[side]}) が見つかりません。"
                    "リポジトリ側で削除された可能性があります"
                )
        fo, fn = by_uid[job_input["old_uid"]], by_uid[job_input["new_uid"]]
        old = load_snapshot(repo.download(fo).path, config=config,
                            meta=fo.snapshot_meta())
        new = load_snapshot(repo.download(fn).path, config=config,
                            meta=fn.snapshot_meta())
        pair_feed_info = {
            "org": job_input["org"], "feed": job_input["feed"],
            "old_uid": fo.uid, "new_uid": fn.uid,
            "old_from_date": fo.from_date, "new_from_date": fn.from_date,
        }
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

    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    bundle = build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta)
    import gtfs_semantic_diff.report as report_pkg

    template = (Path(report_pkg.__file__).parent / "viewer_template.html").read_text(
        "utf-8"
    )
    html = render_html(bundle, template)

    if pair_feed_info is None:  # アップロード由来: ランダム URL・30日削除
        result_key = f"r/anon/{job_id}.html"
        _put_html(result_key, html, cache="public, max-age=300")
        return result_key
    return _write_versioned(job_id, html, pair_feed_info)


def _put_html(key: str, html: str, cache: str) -> None:
    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl=cache,
    )


def _write_versioned(pair: str, html: str, feed_info: dict) -> str:
    """版として不変保存 + 入口 (最新版コピー) + index.json 更新。設計: web.md W3-2 詳細方針。

    index.json の read-modify-write に排他は掛けない (同版の同時生成は同一内容の
    上書きで無害。異版の競合はツールデプロイと重なった一瞬のみで、次回投入で自癒する)。
    """
    import datetime

    version = _tool_version()
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    # 版は不変 (ブラウザ・CloudFront に長期キャッシュさせる)
    _put_html(versioning.version_key(pair, version), html,
              cache="public, max-age=31536000, immutable")
    index = versioning.update_index(
        _get_index(pair), pair=pair, version=version,
        generated_at=generated_at, feed_info=feed_info,
    )
    # 入口は最新版のコピー。自分が最新のときだけ上書きする
    # (ロールバック運用中に旧版が最新入口を巻き戻さないように)
    if index["latest"] == version:
        _put_html(versioning.entry_key(pair), html, cache="public, max-age=300")
    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=versioning.index_key(pair),
        Body=json.dumps(index, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
        CacheControl="public, max-age=60",
    )
    return versioning.entry_key(pair)
