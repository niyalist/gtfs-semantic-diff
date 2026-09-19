"""AN2: CloudFront 標準ログ集計 (scripts/access_stats.py) と MCP 利用記録
(infra/runtime/mcp_entry.request_log_fields) の単体テスト。

出力に IP が混じらないこと、URI/UA の分類、日別ユニーク数の数え方を
合成ログで固定する (docs/ops/analytics.md)。
"""
from __future__ import annotations

import importlib.util
import json
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "access_stats", ROOT / "scripts" / "access_stats.py")
access_stats = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(access_stats)

FIELDS = ("date time x-edge-location sc-bytes c-ip cs-method cs(Host) cs-uri-stem "
          "sc-status cs(Referer) cs(User-Agent) cs-uri-query cs(Cookie) x-edge-result-type "
          "x-edge-request-id x-host-header cs-protocol cs-bytes time-taken").split()
PAIR = "nagai-unyu__Nagaibus__4a4a81e7__b1be1add"
CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


def _line(date="2026-09-20", ip="203.0.113.7", method="GET", path="/", status="200",
          ref="-", ua=CHROME, edge="NRT57-P1", nbytes="1234"):
    rec = {
        "date": date, "time": "01:02:03", "x-edge-location": edge, "sc-bytes": nbytes,
        "c-ip": ip, "cs-method": method, "cs(Host)": "d22.cloudfront.net",
        "cs-uri-stem": path, "sc-status": status, "cs(Referer)": ref,
        "cs(User-Agent)": urllib.parse.quote(ua), "cs-uri-query": "-", "cs(Cookie)": "-",
        "x-edge-result-type": "Hit", "x-edge-request-id": "x", "x-host-header": "diff.gtfs.jp",
        "cs-protocol": "https", "cs-bytes": "100", "time-taken": "0.01",
    }
    return "\t".join(rec[f] for f in FIELDS)


def _log(lines):
    return "#Version: 1.0\n#Fields: " + " ".join(FIELDS) + "\n" + "\n".join(lines) + "\n"


def test_classify_path_report_keys():
    c = access_stats.classify_path
    assert c(f"/r/{PAIR}.html") == ("report_entry", PAIR)
    assert c(f"/r/{PAIR}/v/2026.9.15.5.html") == ("report_version", PAIR)
    assert c(f"/r/{PAIR}/v/2026.9.15.5.json") == ("render", PAIR)
    assert c(f"/r/{PAIR}/v/2026.9.15.5.events.json") == ("events", PAIR)
    assert c(f"/r/{PAIR}/v/2026.9.15.5.digest.en.md") == ("digest", PAIR)
    assert c(f"/r/{PAIR}/v/2026.9.15.5.routes.digest.json") == ("routes_digest", PAIR)
    assert c(f"/r/{PAIR}.digest.md") == ("digest", PAIR)       # 入口エイリアス
    assert c(f"/r/{PAIR}/index.json") == ("ledger", PAIR)
    assert c("/r/u/u-0a1b2c3d4e5f.html") == ("report_entry", "(upload:u)")
    assert c("/r/anon/anon-0a1b2c.json") == ("render", "(upload:anon)")
    assert c("/r/u/u-0a1b2c.mapping.json") == ("mapping", "(upload:u)")
    assert c("/") == ("top", "")
    assert c("/index.html") == ("top", "")
    assert c("/admin.html") == ("admin", "")
    assert c("/mcp") == ("mcp", "")
    assert c("/api/jobs/abc-123") == ("api", "/api/jobs/{id}")
    assert c("/api/feeds") == ("api", "/api/feeds")
    assert c("/docs/reference.md") == ("docs", "/docs/reference.md")
    assert c("/feeds/nagai-unyu__Nagaibus.json") == ("feed_ledger", "nagai-unyu__Nagaibus")
    assert c("/favicon.svg") == ("asset", "")
    assert c("/wp-login.php") == ("other", "")


def test_classify_ua():
    c = access_stats.classify_ua
    assert c(CHROME) == ("browser", "")
    assert c("Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)") \
        == ("ai_agent", "ChatGPT-User")
    assert c("Mozilla/5.0 (compatible; GPTBot/1.2)") == ("ai_crawler", "GPTBot")
    assert c("Mozilla/5.0 AppleWebKit/537.36 (compatible; Googlebot/2.1)") \
        == ("crawler", "Googlebot")
    assert c("Mozilla/5.0 (compatible; Applebot-Extended/0.1)")[1] == "Applebot-Extended"
    assert c("python-httpx/0.28.1") == ("program", "python-httpx")
    assert c("curl/8.7.1") == ("program", "curl")
    assert c("Twitterbot/1.0") == ("preview", "Twitterbot")
    assert c("gtfs-semdiff-mcp") == ("internal", "mcp-server")  # 本番実ログで確認 (2026-09-19)
    assert c("SomethingScraper/2.0") == ("bot", "SomethingScraper")
    assert c("-") == ("other", "")


def test_stats_counts_and_no_ip_leak():
    ua_bot = "Mozilla/5.0 (compatible; ChatGPT-User/1.0)"
    lines = [
        # 人 A: トップ → レポート入口 → 描画 (viewer data)
        _line(path="/", ref="https://x.com/someone/status/1"),
        _line(path=f"/r/{PAIR}.html", ref="https://x.com/someone/status/1"),
        _line(path=f"/r/{PAIR}/v/2026.9.15.5.json"),
        # 人 B (別 IP、同日): 版ページを直接
        _line(ip="198.51.100.9", path=f"/r/{PAIR}/v/2026.9.15.5.html",
              ref="https://diff.gtfs.jp/"),  # 自サイト → 流入元に数えない
        _line(ip="198.51.100.9", path=f"/r/{PAIR}/v/2026.9.15.5.json"),
        # 人 A 翌日
        _line(date="2026-09-21", path="/", ref="https://www.google.com/"),
        # AI エージェント: HTML と digest (描画しない)
        _line(ip="192.0.2.1", path=f"/r/{PAIR}.html", ua=ua_bot),
        _line(ip="192.0.2.1", path=f"/r/{PAIR}.digest.md", ua=ua_bot),
        # MCP と API、404、アセット
        _line(ip="192.0.2.2", method="POST", path="/mcp", ua="python-httpx/0.28"),
        _line(ip="192.0.2.2", path="/api/jobs/abc", ua="python-httpx/0.28"),
        _line(path="/nope.html", status="404"),
        _line(path="/favicon.svg"),
    ]
    st = access_stats.Stats()
    for rec in access_stats.parse_log(_log(lines)):
        st.add(rec)
    res = st.result()
    assert res["total_requests"] == 12
    assert res["status"]["404"] == 1
    d20, d21 = res["days"]["2026-09-20"], res["days"]["2026-09-21"]
    assert d20["visitors"] == 2 and d20["renders"] == 2 and d20["mcp"] == 1 and d20["api"] == 1
    assert d21["visitors"] == 1 and d21["renders"] == 0
    assert res["kinds_200"]["report_entry"] == 2          # 人 + エージェント
    assert res["kinds_200_browser"]["report_entry"] == 1  # 人だけ
    assert res["kinds_200"]["digest"] == 1
    top = res["reports"][0]
    assert top["pair"] == PAIR and top["render"] == 2 and top["report_entry"] == 2
    assert res["referrers"] == {"x.com": 2, "www.google.com": 1}
    kinds = {(c["kind"], c["name"]) for c in res["clients"]}
    assert ("ai_agent", "ChatGPT-User") in kinds and ("program", "python-httpx") in kinds
    assert res["client_kinds_by_page_kind"]["report_entry"] == {"browser": 1, "ai_agent": 1}
    assert res["api_paths"] == {"GET /api/jobs/{id}": 1}
    assert res["edges"] == {"NRT": 12}
    # IP は JSON にも Markdown にも出ない
    dump = json.dumps(res) + access_stats.render_markdown(res, "t")
    for ip in ("203.0.113.7", "198.51.100.9", "192.0.2.1", "192.0.2.2"):
        assert ip not in dump


def test_parse_log_tolerates_short_and_comment_lines():
    text = _log([_line(), "#comment", "short\tline"])
    assert len(list(access_stats.parse_log(text))) == 1


def test_mcp_request_log_fields():
    # mcp_entry は import 時に MCP サーバーを組み立てる (mcp SDK が要る)。
    # infra/runtime は test_mcp_server.py と同じく sys.path に載せる
    import sys

    import pytest

    pytest.importorskip("mcp")
    sys.path.insert(0, str(ROOT / "infra" / "runtime"))
    try:
        import mcp_entry
    finally:
        sys.path.pop(0)
    f = mcp_entry.request_log_fields
    hdr = {"User-Agent": "python-httpx/0.28", "X-Forwarded-For": "203.0.113.7"}
    call = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "get_digest",
                                  "arguments": {"pair": PAIR, "lang": "ja",
                                                "query": "秘密の自由文"}}}).encode()
    rec = f(call, hdr)
    assert rec == {"mcp": "tools/call", "ua": "python-httpx/0.28", "tool": "get_digest",
                   "args": {"pair": PAIR, "lang": "ja"}}
    assert "203.0.113.7" not in json.dumps(rec) and "秘密" not in json.dumps(rec)
    init = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                       "params": {"clientInfo": {"name": "claude-ai", "version": "1.2"}}}
                      ).encode()
    assert f(init, hdr)["client"] == "claude-ai"
    assert f(b'{"jsonrpc":"2.0","method":"tools/list","id":2}', hdr) is None
    assert f(b"not json", hdr) is None
    assert f(b"[1,2]", hdr) is None
