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
import webusers
from boto3.dynamodb.conditions import Key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import os  # noqa: E402

RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET", "")
JOBS_TABLE = os.environ.get("JOBS_TABLE", "")
USERDATA_TABLE = os.environ.get("USERDATA_TABLE", "")
FEEDBACK_TABLE = os.environ.get("FEEDBACK_TABLE", "")
ADMIN_EMAILS = os.environ.get("ADMIN_EMAILS", "")
FEEDBACK_EMAIL = os.environ.get("FEEDBACK_EMAIL", "")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
GOOGLE_LOGIN = os.environ.get("GOOGLE_LOGIN", "")
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


def _userdata_table():
    return ddb.Table(USERDATA_TABLE)


def _json_default(v):
    """DynamoDB (boto3 resource) は数値を Decimal で返すため JSON 化時に変換する。"""
    import decimal

    if isinstance(v, decimal.Decimal):
        return int(v) if v == int(v) else float(v)
    raise TypeError(f"not JSON serializable: {type(v)}")


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False, default=_json_default),
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
    """版台帳 index.json を読む。未生成なら None。

    読み取りに失敗しても None (= 生成し直す) に倒す — lazy キャッシュの判定は
    最悪でも「余計に1回計算する」で済ませ、投入自体は失敗させない。"""
    import botocore.exceptions

    try:
        obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=versioning.index_key(pair))
    except s3.exceptions.NoSuchKey:
        return None
    except botocore.exceptions.ClientError as e:
        logger.warning("index.json 読み取り失敗 (%s): %s", pair, e)
        return None
    return json.loads(obj["Body"].read())


# --- API ---


def api(event, context):  # noqa: ARG001 - Lambda signature
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "")
    qs = event.get("queryStringParameters") or {}
    try:
        if method == "GET" and path == "/api/config":
            return _api_config()
        if path == "/api/me" or path.startswith("/api/me/"):
            return _api_me(event, method, path, qs)
        if path.startswith("/api/admin"):
            return _api_admin(event, method, path)
        if method == "GET" and path == "/api/gtfs/feeds":
            return _api_feeds(qs)
        if method == "GET" and path == "/api/gtfs/files":
            return _api_files(qs)
        if method == "POST" and path == "/api/uploads":
            return _api_uploads()
        if method == "POST" and path == "/api/feedback":
            return _api_feedback(json.loads(event.get("body") or "{}"))
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


# --- admin (W3 追補: docs/design/admin.md S2) ---
# 認証は /api/me と同じ JWT オーソライザ (API Gateway) + ここでの許可リスト照合。
# 読み取り専用。アップロード zip の中身は出さない (メタのみ — 規約 §3/§4 と整合)


def _api_admin(event, method: str, path: str) -> dict:
    email = _claims(event).get("email", "")
    if not webusers.is_admin(email, ADMIN_EMAILS):
        logger.warning("admin 拒否: %s", email or "(no email)")
        return _resp(403, {"error": "forbidden"})
    if method == "GET" and path == "/api/admin/summary":
        return _api_admin_summary()
    if method == "GET" and path == "/api/admin/pairs":
        return _api_admin_pairs()
    return _resp(404, {"error": "not found"})


def _scan_all(table, **kwargs) -> list:
    items, resp = [], table.scan(**kwargs)
    items += resp.get("Items", [])
    while "LastEvaluatedKey" in resp and len(items) < 5000:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items += resp.get("Items", [])
    return items


def _api_admin_summary() -> dict:
    """アカウント・ジョブ・保存 zip・フィードバックの一覧 (規模が小さい前提の Scan)。"""
    users, zips = [], []
    for it in _scan_all(_userdata_table()):
        if it.get("sk") == "profile":
            users.append({"user_id": it.get("user_id"), "email": it.get("email"),
                          "created_at": it.get("created_at"),
                          "last_seen_at": it.get("last_seen_at")})
        elif str(it.get("sk", "")).startswith("zip#"):
            zips.append({"user_id": it.get("user_id"),
                         "display_name": it.get("display_name"),
                         "size": it.get("size"), "created_at": it.get("created_at"),
                         "source_name": it.get("source_name")})
    jobs = sorted(
        _scan_all(_jobs_table()),
        key=lambda it: int(it.get("created_at", 0)), reverse=True)[:300]
    feedback = sorted(
        _scan_all(ddb.Table(FEEDBACK_TABLE)),
        key=lambda it: str(it.get("created_at", "")), reverse=True)[:200]
    users.sort(key=lambda u: u.get("created_at") or 0, reverse=True)
    zips.sort(key=lambda z: str(z.get("created_at", "")), reverse=True)
    return _resp(200, {"users": users, "jobs": jobs, "zips": zips,
                       "feedback": feedback})


def _api_admin_pairs() -> dict:
    """生成済みの正準ペア一覧 (S3 の r/{pair}/index.json を歩く)。
    「どの差分が求められているか」のビュー。"""
    pairs = []
    paginator = s3.get_paginator("list_objects_v2")
    prefixes = []
    for page in paginator.paginate(Bucket=RESULTS_BUCKET, Prefix="r/",
                                   Delimiter="/"):
        for p in page.get("CommonPrefixes", []):
            name = p["Prefix"]  # "r/{pair}/"
            if name in ("r/anon/", "r/u/"):
                continue
            prefixes.append(name)
    for prefix in prefixes[:300]:
        try:
            obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=f"{prefix}index.json")
            idx = json.loads(obj["Body"].read())
        except Exception:  # index なし (旧形式) は pair 名だけ
            pairs.append({"pair": prefix[2:-1]})
            continue
        latest = next((v for v in idx.get("versions", [])
                       if v.get("version") == idx.get("latest")), {})
        pairs.append({
            "pair": idx.get("pair", prefix[2:-1]),
            "feed": idx.get("feed", {}),
            "version_count": len(idx.get("versions", [])),
            "latest": idx.get("latest"),
            "generated_at": latest.get("generated_at"),
        })
    pairs.sort(key=lambda p: str(p.get("generated_at") or ""), reverse=True)
    return _resp(200, {"pairs": pairs, "truncated": len(prefixes) > 300})


def _api_config() -> dict:
    """フロントに認証設定を渡す (公開)。Google IdP 未接続ならログイン UI を出さない。"""
    return _resp(200, {
        "login_enabled": bool(GOOGLE_LOGIN and COGNITO_DOMAIN and COGNITO_CLIENT_ID),
        "cognito_domain": COGNITO_DOMAIN,
        "client_id": COGNITO_CLIENT_ID,
    })


def _claims(event) -> dict:
    """JWT オーソライザ (API Gateway) が検証済みのクレームを取り出す。"""
    return (event.get("requestContext", {}).get("authorizer", {})
            .get("jwt", {}).get("claims", {}))


def _api_me(event, method: str, path: str, qs: dict) -> dict:
    """ログイン必須 API 群。認証は API Gateway の JWT オーソライザが済ませている
    (このパスに素の HTTP API 経由で来た場合のみ claims が空 → 401)。"""
    claims = _claims(event)
    email = claims.get("email", "")
    if not email:
        return _resp(401, {"error": "unauthorized"})
    user_id = webusers.user_id_from_email(email)
    _ensure_user(user_id, email)
    if method == "GET" and path == "/api/me":
        return _resp(200, {"user_id": user_id, "email": email})
    if method == "GET" and path == "/api/me/history":
        return _api_me_history(user_id)
    if method == "GET" and path == "/api/me/zips":
        return _api_me_zips(user_id)
    if method == "POST" and path == "/api/me/jobs":
        body = json.loads(event.get("body") or "{}")
        return _api_submit(body, user_id=user_id)
    if method == "DELETE" and path == "/api/me/history":
        return _api_me_history_delete(user_id, qs.get("sk", ""))
    if method == "DELETE" and path == "/api/me/zips":
        return _api_me_zip_delete(user_id, qs.get("id", ""))
    return _resp(404, {"error": "not found"})


def _ensure_user(user_id: str, email: str) -> None:
    """内部 user_id の台帳 (profile 行) を lazy に upsert する。"""
    _userdata_table().update_item(
        Key={"user_id": user_id, "sk": "profile"},
        UpdateExpression=(
            "SET email = :e, last_seen_at = :t, "
            "created_at = if_not_exists(created_at, :t)"
        ),
        ExpressionAttributeValues={":e": email, ":t": int(time.time())},
    )


def _api_me_history(user_id: str) -> dict:
    res = _userdata_table().query(
        KeyConditionExpression=(
            Key("user_id").eq(user_id) & Key("sk").begins_with("run#")
        ),
        ScanIndexForward=False,  # sk = run#{ISO時刻}#… なので新しい順
        Limit=200,
    )
    items = [{k: v for k, v in it.items() if k != "user_id"}
             for it in res.get("Items", [])]
    return _resp(200, {"items": items})


def _api_me_zips(user_id: str) -> dict:
    res = _userdata_table().query(
        KeyConditionExpression=(
            Key("user_id").eq(user_id) & Key("sk").begins_with("zip#")
        ),
    )
    items = sorted(
        ({k: v for k, v in it.items() if k != "user_id"}
         for it in res.get("Items", [])),
        key=lambda it: it.get("created_at", ""), reverse=True,
    )
    return _resp(200, {"items": items})


def _api_me_history_delete(user_id: str, sk: str) -> dict:
    """履歴1件の削除。リポジトリ由来は行のみ (共通の公開結果は残す)。
    アップロード由来は本人の結果レポート (r/u/) も削除する。"""
    if not sk.startswith("run#"):
        return _bad("invalid history key")
    table = _userdata_table()
    item = table.get_item(Key={"user_id": user_id, "sk": sk}).get("Item")
    if not item:
        return _resp(404, {"error": "not found"})
    result_url = str(item.get("result_url", ""))
    if item.get("kind") == "upload" and result_url.startswith("/r/u/"):
        s3.delete_object(Bucket=RESULTS_BUCKET, Key=result_url[1:])
        # RD1b: 分離データ JSON も対で削除 (旧レポートには存在しないが無害)
        if result_url.endswith(".html"):
            s3.delete_object(
                Bucket=RESULTS_BUCKET, Key=result_url[1:-5] + ".json"
            )
    table.delete_item(Key={"user_id": user_id, "sk": sk})
    return _resp(200, {"ok": True})


def _api_me_zip_delete(user_id: str, zip_id: str) -> dict:
    """保存 zip の削除 (台帳と S3 実体の両方)。"""
    sk = webusers.zip_sk(_safe_id(zip_id))
    table = _userdata_table()
    item = table.get_item(Key={"user_id": user_id, "sk": sk}).get("Item")
    if not item:
        return _resp(404, {"error": "not found"})
    s3_key = str(item.get("s3_key", ""))
    if s3_key.startswith(f"userzips/{user_id}/"):
        s3.delete_object(Bucket=RESULTS_BUCKET, Key=s3_key)
    table.delete_item(Key={"user_id": user_id, "sk": sk})
    return _resp(200, {"ok": True})


def _api_feedback(body: dict) -> dict:
    """結果ページからの問題報告 (匿名可・W3-2c)。DynamoDB へ恒久記録し、
    通知先が設定されていれば SES で自分宛てにメールする (失敗しても記録は残す)。"""
    import datetime

    message = str(body.get("message", "")).strip()
    if not message:
        return _bad("報告内容が空です")
    item = {
        "feedback_id": f"fb-{secrets.token_hex(6)}",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"),
        "result_url": str(body.get("result_url", ""))[:300],
        "event_id": str(body.get("event_id", ""))[:100],
        "message": message[:4000],
    }
    ddb.Table(FEEDBACK_TABLE).put_item(Item=item)
    if FEEDBACK_EMAIL:
        try:
            boto3.client("ses").send_email(
                Source=FEEDBACK_EMAIL,
                Destination={"ToAddresses": [FEEDBACK_EMAIL]},
                Message={
                    "Subject": {"Data": "[gtfs-semdiff] フィードバック",
                                "Charset": "UTF-8"},
                    "Body": {"Text": {"Charset": "UTF-8", "Data": (
                        f"result: {item['result_url']}\n"
                        f"event:  {item['event_id']}\n"
                        f"id:     {item['feedback_id']}\n\n"
                        f"{item['message']}\n")}},
                },
            )
        except Exception:
            logger.exception("SES 送信失敗 (記録済み: %s)", item["feedback_id"])
    return _resp(200, {"ok": True, "feedback_id": item["feedback_id"]})


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


def _record_history(user_id: str, job_id: str, kind: str,
                    result_url: str, extra: dict) -> str:
    """ログインユーザーの比較履歴 (run# 行) を記録し sk を返す。"""
    import datetime

    created = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")
    sk = webusers.history_sk(created, job_id)
    item = {"user_id": user_id, "sk": sk, "kind": kind, "job_id": job_id,
            "result_url": result_url, "created_at": created}
    item.update({k: str(v)[:120] for k, v in extra.items() if v})
    _userdata_table().put_item(Item=item)
    return sk


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


def _api_submit(body: dict, user_id: str | None = None) -> dict:
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
        if user_id:
            _record_history(user_id, job_id, "repo",
                            f"/{versioning.entry_key(job_id)}", {
                                "org": org, "feed": feed,
                                "old_uid": old_uid, "new_uid": new_uid,
                                "org_name": body.get("org_name", ""),
                                "feed_name": body.get("feed_name", ""),
                                "old_from_date": body.get("old_from_date", ""),
                                "new_from_date": body.get("new_from_date", ""),
                            })
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
        sides = {}
        save = []
        for side in ("old", "new"):
            key = body.get(f"{side}_key", "")
            zip_id = body.get(f"{side}_zip_id", "")
            if key:
                if not key.startswith("uploads/"):
                    return _bad("invalid upload keys")
                sides[side] = key
                if user_id:
                    save.append(side)  # 新規アップロードは保存して再利用可能に
            elif zip_id and user_id:
                # 保存済み zip の再利用 (自分の台帳にある場合のみ)
                rec = _userdata_table().get_item(
                    Key={"user_id": user_id,
                         "sk": webusers.zip_sk(_safe_id(zip_id))}
                ).get("Item")
                if not rec:
                    return _bad("保存済みデータが見つかりません")
                sides[side] = rec["s3_key"]
            else:
                return _bad("invalid upload keys")
        prefix = "u" if user_id else "anon"
        job_id = f"{prefix}-{secrets.token_hex(6)}"
        status_url = f"/api/jobs/{urllib.parse.quote(job_id)}"
        job_input = {"type": input_type,
                     "old_key": sides["old"], "new_key": sides["new"],
                     "user_id": user_id or "", "save": save,
                     "old_name": str(body.get("old_name", ""))[:120],
                     "new_name": str(body.get("new_name", ""))[:120]}
        if user_id:
            # ログイン = 恒久 URL (r/u/、ライフサイクル削除なし)。
            # 表示名は worker が zip の中身から自動生成して履歴に書き戻す
            job_input["history_sk"] = _record_history(
                user_id, job_id, "upload", f"/r/u/{job_id}.html", {
                    "old_name": body.get("old_name", ""),
                    "new_name": body.get("new_name", ""),
                })
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
    t0 = int(time.time())
    _update(job_id, status="running", running_since=t0)
    try:
        result_key = _run_compare(job_id, job_input)
        now = int(time.time())
        _update(job_id, status="succeeded", result_url=f"/{result_key}",
                finished_at=now, duration_s=now - t0)
        logger.info("job %s succeeded: %s (%ds)", job_id, result_key, now - t0)
    except Exception as e:
        logger.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
        now = int(time.time())
        _update(job_id, status="failed", error=str(e)[:500],
                finished_at=now, duration_s=now - t0)


def _run_compare(job_id: str, job_input: dict) -> str:
    from gtfs_semantic_diff.config import Config
    from gtfs_semantic_diff.events.pipeline import compare_snapshots_with_artifacts
    from gtfs_semantic_diff.load import GtfsDataRepository, load_snapshot
    from gtfs_semantic_diff.report.bundle import build_bundle, write_html_split

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
        if job_input.get("user_id"):
            _save_user_zips(job_input, {"old": old, "new": new})

    event_set, rawdiffs, identity, trip_delta = compare_snapshots_with_artifacts(
        old, new, config
    )
    # Web 配信は core バンドル (RD1a): rawdiffs 全量を持たず evidence/生差分は
    # サンプル+件数。行レベルの完全データは CLI --html / 生データ DL (RD2) で
    bundle = build_bundle(old, new, config, event_set, rawdiffs, identity, trip_delta,
                          core=True)
    # バンドル構築後はスナップショット等を解放する。HTML 書き出し中に pandas
    # テーブル (GB 級) を抱えたままにすると 3008MB の Lambda を圧迫する (IN-3)
    del old, new, event_set, identity, trip_delta, rawdiffs
    import gtfs_semantic_diff.report as report_pkg

    template = (Path(report_pkg.__file__).parent / "viewer_template.html").read_text(
        "utf-8"
    )
    # RD1b: アプリ HTML とデータ JSON (gzip) を分離。data_url はサイト相対の
    # 絶対パス (入口と版の両方から同じ HTML コピーが参照するため)。
    # ペイロードはファイルへ逐次書き出し → upload_file (IN-3)
    html_path = "/tmp/result.html"
    data_path = "/tmp/result.json.gz"
    if pair_feed_info is None:
        # アップロード由来: ランダム URL。匿名 = r/anon/ (30日削除)、
        # ログイン = r/u/ (恒久、削除ライフサイクルなし)
        prefix = "r/u" if job_input.get("user_id") else "r/anon"
        write_html_split(bundle, template, html_path, data_path,
                         data_url=f"/{prefix}/{job_id}.json")
        _put_json_file(f"{prefix}/{job_id}.json", data_path,
                       cache="public, max-age=300")
        result_key = f"{prefix}/{job_id}.html"
        _put_html_file(result_key, html_path, cache="public, max-age=300")
        return result_key
    version = _tool_version()
    write_html_split(bundle, template, html_path, data_path,
                     data_url="/" + versioning.data_key(job_id, version))
    return _write_versioned(job_id, html_path, data_path, version, pair_feed_info)


def _snapshot_label_parts(snapshot) -> tuple[str, str]:
    """保存 zip の表示名の素材 (agency_name, 開始日) を GTFS の中身から得る。
    欠損はすべて空文字に倒す (webusers.zip_display_name がフォールバックする)。"""

    def cell(df, col):
        if df is None or not len(df) or col not in df.columns:
            return ""
        v = str(df.iloc[0][col]).strip()
        return "" if v.lower() in ("nan", "none") else v

    name = cell(snapshot.table("agency"), "agency_name")
    from_date = cell(snapshot.table("feed_info"), "feed_start_date")
    if not from_date:
        cal = snapshot.table("calendar")
        if cal is not None and len(cal) and "start_date" in cal.columns:
            from_date = str(cal["start_date"].min())
    if not from_date:
        cd = snapshot.table("calendar_dates")
        if cd is not None and len(cd) and "date" in cd.columns:
            from_date = str(cd["date"].min())
    if len(from_date) == 8 and from_date.isdigit():
        from_date = f"{from_date[:4]}-{from_date[4:6]}-{from_date[6:]}"
    elif not (len(from_date) == 10 and from_date.count("-") == 2):
        from_date = ""
    return name, from_date


def _save_user_zips(job_input: dict, snaps: dict) -> None:
    """ログインユーザーの新規アップロード zip を userzips/ へ複製して台帳に載せ、
    自動生成した表示名を履歴 (run# 行) にも書き戻す (決定 §6-4)。"""
    import datetime

    user_id = job_input["user_id"]
    now = datetime.datetime.now(datetime.timezone.utc)
    created = now.isoformat(timespec="seconds")
    # 表示名に焼き込む日付はユーザー向けなので JST (データの created_at は UTC)
    jst = now.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
    labels = {}
    for side in ("old", "new"):
        name, from_date = _snapshot_label_parts(snaps[side])
        src_name = job_input.get(f"{side}_name", "") or f"{side}.zip"
        label = webusers.zip_display_name(name, from_date,
                                          jst.isoformat(timespec="seconds"),
                                          fallback=src_name)
        labels[side] = label
        if side not in job_input.get("save", []):
            continue  # 保存済み zip の再利用分は複製しない
        zip_id = secrets.token_hex(6)
        dest = webusers.zip_s3_key(user_id, zip_id)
        src = job_input[f"{side}_key"]
        s3.copy_object(Bucket=RESULTS_BUCKET, Key=dest,
                       CopySource={"Bucket": RESULTS_BUCKET, "Key": src})
        head = s3.head_object(Bucket=RESULTS_BUCKET, Key=dest)
        _userdata_table().put_item(Item={
            "user_id": user_id, "sk": webusers.zip_sk(zip_id),
            "zip_id": zip_id, "display_name": label, "s3_key": dest,
            "size": head["ContentLength"], "created_at": created,
            "source_name": src_name,
        })
    if job_input.get("history_sk"):
        _userdata_table().update_item(
            Key={"user_id": user_id, "sk": job_input["history_sk"]},
            UpdateExpression="SET old_label = :o, new_label = :n",
            ExpressionAttributeValues={":o": labels["old"], ":n": labels["new"]},
        )


def _put_html(key: str, html: str, cache: str) -> None:
    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl=cache,
    )


def _put_html_file(key: str, path: str, cache: str) -> None:
    """ファイルからのストリーミングアップロード (encode 済み全量を持たない。IN-3)。"""
    s3.upload_file(
        path, RESULTS_BUCKET, key,
        ExtraArgs={
            "ContentType": "text/html; charset=utf-8",
            "CacheControl": cache,
        },
    )


def _put_json_file(key: str, path: str, cache: str) -> None:
    """gzip 済みデータ JSON のアップロード (RD1b)。

    Content-Encoding: gzip を付けて格納 — CloudFront の自動圧縮は 10MB 超に
    効かないため、生成時に圧縮しておく。"""
    s3.upload_file(
        path, RESULTS_BUCKET, key,
        ExtraArgs={
            "ContentType": "application/json; charset=utf-8",
            "ContentEncoding": "gzip",
            "CacheControl": cache,
        },
    )


def _write_versioned(pair: str, html_path: str, data_path: str, version: str,
                     feed_info: dict) -> str:
    """版として不変保存 + 入口 (最新版コピー) + index.json 更新。設計: web.md W3-2 詳細方針。

    index.json の read-modify-write に排他は掛けない (同版の同時生成は同一内容の
    上書きで無害。異版の競合はツールデプロイと重なった一瞬のみで、次回投入で自癒する)。
    """
    import datetime

    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    # 版は不変 (ブラウザ・CloudFront に長期キャッシュさせる)。データ JSON が先
    # (HTML が参照するため、逆順だと一瞬 404 になりうる)
    _put_json_file(versioning.data_key(pair, version), data_path,
                   cache="public, max-age=31536000, immutable")
    _put_html_file(versioning.version_key(pair, version), html_path,
                   cache="public, max-age=31536000, immutable")
    index = versioning.update_index(
        _get_index(pair), pair=pair, version=version,
        generated_at=generated_at, feed_info=feed_info,
    )
    # 入口は最新版のコピー。自分が最新のときだけ上書きする
    # (ロールバック運用中に旧版が最新入口を巻き戻さないように)
    if index["latest"] == version:
        _put_html_file(versioning.entry_key(pair), html_path, cache="public, max-age=300")
    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=versioning.index_key(pair),
        Body=json.dumps(index, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
        CacheControl="public, max-age=60",
    )
    return versioning.entry_key(pair)
