"""MCP サーバー (RD4c-1a) の contract test。

- mcp_tools: 純ロジック (偽 Site 注入) — 上限・省略明示・エラー形
- mcp_entry: Starlette TestClient で新旧両世代のプロトコルを実際に叩く
  (SDK 更新の受け入れ条件 — mcp.md §6)

mcp SDK が未導入の環境では protocol テストのみ skip する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "infra" / "runtime"))

import mcp_tools as T  # noqa: E402


class FakeSite(T.Site):
    def __init__(self, pages: dict):
        self.pages = pages
        self.origin = "https://example.test"

    def _fetch(self, path):
        v = self.pages.get(path)
        if v is None:
            return None
        return v.encode() if isinstance(v, str) else json.dumps(v).encode()

    def head_length(self, path):
        v = self.pages.get(path)
        if v is None:
            return None
        return len(json.dumps(v)) if not isinstance(v, str) else len(v)


def test_tools_pure_logic():
    site = FakeSite({
        "/r/p1.digest.md": "# 差分ダイジェスト: X",
        "/r/p1.digest.json": {
            "routes": [{"name": "A線", "day_totals": [], "changes": []}],
            "routes_unchanged": 2,
            "stop_changes": {"renamed": [{"old": "a", "new": "b", "routes": []}]},
            "verification": {"explained_ratio": 1.0},
        },
        "/r/p1.routes.digest.json": {"routes": {"A線": {"day_totals": [],
                                                        "time_bands": {}}}},
        "/r/p1.mapping.json": {
            "note": "n",
            "stops": [{"relation": "renamed",
                       "old": {"name": "甲", "stop_ids": ["S1"]},
                       "new": {"name": "乙", "stop_ids": ["S1"]}}],
            "routes": [], "trips": [{"relation": "exact", "old": "t1", "new": "t1"}],
        },
        "/r/p1/index.json": {"versions": [{
            "version": "1", "key": "r/p1/v/1.html",
            "artifacts": {"events": {"url": "/r/p1/v/1.events.json"}}}]},
        "/r/p1/v/1.events.json": {
            "events": [{"event_id": "e1", "type": "STOP_RENAMED",
                        "severity": "minor", "subject": {"stop_cluster": "甲"},
                        "evidence": ["r1", "r2"]}],
            "accounting": {"explained_ratio": 1.0},
        },
    })
    assert T.get_digest(site, "p1").startswith("# 差分ダイジェスト")
    assert T.list_routes(site, "p1")["routes_unchanged"] == 2
    assert "A線" in T.get_route_detail(site, "p1", "A線")["route_group"]
    with pytest.raises(ValueError, match="候補"):
        T.get_route_detail(site, "p1", "無い線")
    m = T.map_ids(site, "p1", stop_id="S1")
    assert m["matches"]["stops"]["total"] == 1
    ev = T.get_events(site, "p1", type="STOP_RENAMED")
    assert ev["matched"] == 1 and ev["events"][0]["evidence_count"] == 2
    assert "evidence" not in ev["events"][0]
    # 不在ペアはガイダンス付きエラー
    with pytest.raises(ValueError, match="list_pairs"):
        T.get_digest(site, "nope")


def test_map_ids_cap_and_truncation_note():
    stops = [{"relation": "continued",
              "old": {"name": f"停{i}", "stop_ids": [f"S{i}"]},
              "new": {"name": f"停{i}", "stop_ids": [f"S{i}"]}}
             for i in range(30)]
    site = FakeSite({"/r/p.mapping.json": {"stops": stops, "routes": [],
                                            "trips": []}})
    m = T.map_ids(site, "p", name="停")
    assert m["matches"]["stops"]["total"] == 30
    assert len(m["matches"]["stops"]["items"]) == T.MATCH_LIMIT
    assert m["matches"]["stops"]["truncated"] is True


# --- プロトコル (新旧両世代) ---

pytest.importorskip("mcp", reason="mcp SDK 未導入 (contract test は実装環境で)")
pytest.importorskip("httpx")


def _run(coro):
    import asyncio

    return asyncio.run(asyncio.wait_for(coro, 60))


async def _with_app(fn):
    import httpx

    import mcp_entry

    app = mcp_entry.build_app()
    # ASGITransport は lifespan を回さないため手動で (本番は Mangum "auto")
    async with app.router.lifespan_context(app):
        async with httpx.ASGITransport(app=app) as tr:
            async with httpx.AsyncClient(transport=tr, base_url="http://t") as c:
                return await fn(c)


def _modern_headers(method):
    return {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method,
            "Accept": "application/json, text/event-stream"}


def _modern_meta():
    return {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "0"},
            "io.modelcontextprotocol/clientCapabilities": {}}


def test_modern_tools_list():
    async def go(c):
        r = await c.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _modern_meta()}},
            headers=_modern_headers("tools/list"))
        assert r.status_code == 200, r.text
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert {"get_digest", "map_ids", "list_pairs", "get_events",
                "get_route_detail"} <= names

    _run(_with_app(go))


def test_legacy_initialize_era():
    async def go(c):
        r = await c.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "legacy", "version": "0"}}},
            headers={"Accept": "application/json, text/event-stream"})
        assert r.status_code == 200, r.text
        result = r.json()["result"]
        assert result["capabilities"]["tools"] is not None
        ver = result["protocolVersion"]
        r2 = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 2,
                                        "method": "tools/list"},
                          headers={"Accept": "application/json, text/event-stream",
                                   "MCP-Protocol-Version": ver})
        assert r2.status_code == 200, r2.text
        names = {t["name"] for t in r2.json()["result"]["tools"]}
        assert "get_digest" in names

    _run(_with_app(go))


def test_lambda_gate_rejects_non_post():
    # Lambda 入口で POST 以外は 405 (旧世代の standalone SSE も遮断)
    import mcp_entry

    for method in ("GET", "DELETE"):
        ev = {"requestContext": {"http": {"method": method}}, "rawPath": "/mcp"}
        r = mcp_entry.lambda_handler(ev, None)
        assert r["statusCode"] == 405
        assert r["headers"]["allow"] == "POST"


def _post_event(payload: dict, headers: dict) -> dict:
    return {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/mcp",
            "headers": {"content-type": "application/json", **headers},
            "body": json.dumps(payload), "isBase64Encoded": False}


def test_lambda_handler_survives_repeated_invocations():
    # 回帰: Mangum はリクエスト毎に lifespan を回し、session manager の
    # 「1インスタンス1回」制約で2回目に落ちた (2026-08-19 本番)。
    # 同一プロセスで新旧世代を交互に3回叩いて全て 200 を確認する
    import mcp_entry

    legacy = _post_event(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"}}},
        {"accept": "application/json, text/event-stream"})
    modern = _post_event(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list",
         "params": {"_meta": _modern_meta()}},
        {"accept": "application/json, text/event-stream",
         "mcp-protocol-version": "2026-07-28", "mcp-method": "tools/list"})
    for i, ev in enumerate([legacy, modern, modern]):
        r = mcp_entry.lambda_handler(ev, None)
        assert r["statusCode"] == 200, (i, r["body"][:300])
    names = {t["name"] for t in
             json.loads(r["body"])["result"]["tools"]}
    assert "get_digest" in names
