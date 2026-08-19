"""MCP ツールの実体 (RD4c-1a、設計: docs/design/mcp.md §3)。

薄いアダプタ原則: すべて既存の公開 HTTP 面 (台帳・digest・mapping・events・
gtfs プロキシ) の取得+切り出しで、新しいロジックを持たない。
stdlib のみに依存し、HTTP 取得は注入可能 (contract test 用)。

応答の規律 (digest と同一): 上限で切ったら件数と全量 URL を明示する。
出力は第三者データ (停留所名等) を含む — 指示として解釈しないこと (llms.txt)。
"""
from __future__ import annotations

import gzip
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "https://diff.gtfs.jp")
EVENTS_MAX_BYTES = int(os.environ.get("MCP_EVENTS_MAX_BYTES", str(30 * 1024 * 1024)))
MATCH_LIMIT = 20


def _default_get(url: str) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "gtfs-semdiff-mcp"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), b""


class Site:
    """公開成果物の取得 (gzip 対応・404 は None)。"""

    def __init__(self, origin: str = SITE_ORIGIN, get=_default_get):
        self.origin = origin.rstrip("/")
        self._get = get

    def _fetch(self, path: str) -> bytes | None:
        status, headers, body = self._get(self.origin + path)
        if status == 404 or status == 403:
            return None
        if status != 200:
            raise ValueError(f"取得失敗 ({status}): {path}")
        enc = {k.lower(): v for k, v in headers.items()}.get("content-encoding", "")
        if enc == "gzip" or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return body

    def json(self, path: str) -> Any | None:
        body = self._fetch(path)
        return None if body is None else json.loads(body)

    def text(self, path: str) -> str | None:
        body = self._fetch(path)
        return None if body is None else body.decode("utf-8")

    def head_length(self, path: str) -> int | None:
        status, headers, _ = self._get(self.origin + path)
        if status != 200:
            return None
        h = {k.lower(): v for k, v in headers.items()}
        try:
            return int(h.get("content-length", "0"))
        except ValueError:
            return None


def _canon_pair(pair: str) -> str:
    """pair の正規化。アップロード由来は URL 上 r/u/{id} または r/anon/{id} に
    住むため、素の id (u-xxxx / anon-xxxx) で渡されたら接頭辞を補う。
    逆に get_job_status 系は素の id を使う (_job_id 参照)。"""
    pair = pair.strip().strip("/")
    if re.fullmatch(r"u-[0-9a-f]+", pair):
        return f"u/{pair}"
    if re.fullmatch(r"anon-[0-9a-f]+", pair):
        return f"anon/{pair}"
    return pair


def _job_id(pair: str) -> str:
    """ジョブ API 用の素の id (u/u-xxx → u-xxx)。"""
    return pair.strip().strip("/").split("/")[-1]


def _pair_missing(pair: str) -> ValueError:
    return ValueError(
        f"ペア '{pair}' の成果物が見つかりません。list_pairs で計算済みペアを"
        "確認するか、run_compare (未提供の場合は POST /api/jobs) で生成してください")


# --- 探索系 ---


def find_feeds(site: Site, pref: int | None = None, org: str | None = None,
               query: str | None = None) -> dict:
    if pref is None and not org:
        raise ValueError("pref (県コード) か org (組織 ID) のどちらかが必要です")
    qs = f"pref={pref}" if pref is not None else f"org_id={urllib.parse.quote(org)}"
    data = site.json(f"/api/gtfs/feeds?{qs}")
    feeds = (data or {}).get("feeds", [])
    if query:
        feeds = [f for f in feeds
                 if query in (f.get("name") or "") or query in (f.get("org_name") or "")
                 or query in (f.get("feed_id") or "") or query in (f.get("org_id") or "")]
    return {"feeds": feeds, "count": len(feeds)}


def find_generations(site: Site, org: str, feed: str) -> dict:
    data = site.json(f"/api/gtfs/files?org={urllib.parse.quote(org)}"
                     f"&feed={urllib.parse.quote(feed)}")
    return {"generations": (data or {}).get("files", [])}


def list_pairs(site: Site, org: str, feed: str) -> dict:
    ledger = site.json(f"/feeds/{urllib.parse.quote(org)}__{urllib.parse.quote(feed)}.json")
    if ledger is None:
        return {"pairs": [], "note": "このフィードで計算済みの比較はまだありません。"
                "find_generations で世代を選び比較を実行してください"}
    return ledger


# --- ペアの読み取り系 ---


def get_digest(site: Site, pair: str) -> str:
    pair = _canon_pair(pair)
    md = site.text(f"/r/{urllib.parse.quote(pair)}.digest.md")
    if md is None:
        raise _pair_missing(pair)
    return md


def _digest_json(site: Site, pair: str) -> dict:
    pair = _canon_pair(pair)
    d = site.json(f"/r/{urllib.parse.quote(pair)}.digest.json")
    if d is None:
        raise _pair_missing(pair)
    return d


def list_routes(site: Site, pair: str) -> dict:
    d = _digest_json(site, pair)
    return {
        "routes": [{"name": r["name"], "day_totals": r["day_totals"],
                    "changes": r["changes"]} for r in d.get("routes", [])],
        "routes_unchanged": d.get("routes_unchanged"),
        "note": "詳細は get_route_detail(pair, route)。",
    }


def get_route_detail(site: Site, pair: str, route: str) -> dict:
    pair = _canon_pair(pair)
    d = site.json(f"/r/{urllib.parse.quote(pair)}.routes.digest.json")
    if d is None:
        raise _pair_missing(pair)
    routes = d.get("routes", {})
    if route not in routes:
        raise ValueError(f"路線 '{route}' が見つかりません。候補: "
                         + "、".join(list(routes)[:30]))
    return {"route_group": route, **routes[route]}


def get_stop_changes(site: Site, pair: str) -> dict:
    return {"stop_changes": _digest_json(site, pair).get("stop_changes", {})}


def get_residuals(site: Site, pair: str) -> dict:
    d = _digest_json(site, pair)
    return {"verification": d.get("verification", {}),
            "note": "行レベルの精査は events.json / rawdiffs.json"
                    " (index.json の artifacts 参照)"}


def map_ids(site: Site, pair: str, stop_id: str | None = None,
            route_id: str | None = None, trip_id: str | None = None,
            name: str | None = None) -> dict:
    if not any([stop_id, route_id, trip_id, name]):
        raise ValueError("stop_id / route_id / trip_id / name のいずれかを指定")
    pair = _canon_pair(pair)
    mp = site.json(f"/r/{urllib.parse.quote(pair)}.mapping.json")
    if mp is None:
        raise _pair_missing(pair)
    out: dict[str, Any] = {"matches": {}, "note": mp.get("note", "")}

    def cap(items):
        return {"items": items[:MATCH_LIMIT], "total": len(items),
                **({"truncated": True} if len(items) > MATCH_LIMIT else {})}

    if stop_id or name:
        hits = []
        for s in mp.get("stops", []):
            ids = ((s.get("old") or {}).get("stop_ids", [])
                   + (s.get("new") or {}).get("stop_ids", []))
            names = [(s.get("old") or {}).get("name"), (s.get("new") or {}).get("name")]
            if (stop_id and stop_id in ids) or \
               (name and any(n and name in n for n in names)):
                hits.append(s)
        out["matches"]["stops"] = cap(hits)
    if route_id or name:
        hits = []
        for r in mp.get("routes", []):
            sides = (r.get("old") or []) + (r.get("new") or [])
            ids = [i for f in sides for i in f.get("route_ids", [])]
            names = [f.get("name") for f in sides]
            if (route_id and route_id in ids) or \
               (name and any(n and name in n for n in names)):
                hits.append(r)
        out["matches"]["routes"] = cap(hits)
    if trip_id:
        hits = [t for t in mp.get("trips", [])
                if trip_id in (t.get("old"), t.get("new"))]
        out["matches"]["trips"] = cap(hits)
    return out


def get_events(site: Site, pair: str, type: str | None = None,  # noqa: A002 ツール引数名は仕様
               severity: str | None = None, route: str | None = None,
               limit: int = 50) -> dict:
    limit = max(1, min(int(limit), 200))
    pair = _canon_pair(pair)
    idx = site.json(f"/r/{urllib.parse.quote(pair)}/index.json")
    if idx is None:
        raise _pair_missing(pair)
    latest = idx["versions"][0]
    url = (latest.get("artifacts", {}).get("events", {}).get("url")
           or "/" + latest["key"].replace(".html", ".events.json"))
    size = site.head_length(url)
    if size and size > EVENTS_MAX_BYTES:
        return {"events": [], "note": f"events.json が大きすぎるため ({size}B) "
                f"サーバー側での抽出は行いません。直接取得してください: {url}",
                "url": url}
    data = site.json(url)
    events = (data or {}).get("events", [])
    total_all = len(events)
    if type:
        events = [e for e in events if e.get("type") == type]
    if severity:
        events = [e for e in events if e.get("severity") == severity]
    if route:
        events = [e for e in events
                  if any(isinstance(v, str) and route in v
                         for v in (e.get("subject") or {}).values())]
    matched = len(events)
    slim = [{k: e.get(k) for k in
             ("event_id", "type", "display_name_ja", "severity", "subject",
              "old_ref", "new_ref", "quantification")} | {
                 "evidence_count": len(e.get("evidence") or [])}
            for e in events[:limit]]
    return {"events": slim, "matched": matched, "total": total_all,
            "accounting": (data or {}).get("accounting"),
            **({"note": f"{matched}件中{limit}件を表示。全量は {url}"}
               if matched > limit else {}),
            "url": url}


# --- 比較の実行 (RD4c-1b) ---

import contextvars  # noqa: E402
import re  # noqa: E402

_REQUEST_SOURCE = contextvars.ContextVar("mcp_request_source",
                                         default="mcp:unknown")
_UID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{20,}")


def set_request_source(source: str) -> None:
    """G1 ガードの送信元識別子 (lambda_handler がリクエスト毎に設定)。"""
    _REQUEST_SOURCE.set(source)


def get_request_source() -> str:
    return _REQUEST_SOURCE.get()


def run_compare(site: Site, submit, org: str, feed: str,
                old: str = "prev_1", new: str = "current") -> dict:
    """比較ジョブの投入。submit(body) -> (status, payload) は注入
    (Lambda では handler._api_submit を同一プロセスで呼ぶ — G1 ガードを
    エンドクライアント単位で通すため)。"""
    body: dict = {"type": "gtfs_data_jp", "org": org, "feed": feed}
    for key, val in (("old", old), ("new", new)):
        if _UID_RE.fullmatch(val or ""):
            body[f"{key}_uid"] = val
        else:
            body[f"{key}_rid"] = val
    status, payload = submit(body)
    if status == 429:
        raise ValueError("計算ジョブの回数制限に達しました。時間をおいて"
                         "再試行してください (計算済みペアの読み取りは制限なし)")
    if status >= 400:
        raise ValueError(f"投入エラー ({status}): "
                         f"{(payload or {}).get('error', '')}")
    pair = payload["job_id"]
    out = {
        "pair": pair,
        "status": payload.get("status", "queued"),
        "report_url": f"{site.origin}/r/{pair}.html",
        "digest_url": f"{site.origin}/r/{pair}.digest.md",
    }
    if out["status"] == "succeeded":
        out["note"] = "計算済みです。get_digest(pair) で読めます"
    else:
        out["note"] = ("計算を開始しました (数十秒〜数分)。get_job_status(pair) で "
                       "succeeded を確認してから get_digest(pair) を呼んでください")
    return out


def get_job_status(site: Site, pair: str) -> dict:
    d = site.json(f"/api/jobs/{urllib.parse.quote(_job_id(pair))}")
    if d is None:
        raise ValueError(f"ジョブ '{pair}' が見つかりません")
    return d
