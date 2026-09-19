"""AN2: CloudFront 標準ログの集計 (docs/ops/analytics.md)。

クライアント側の計測タグを置かない方針のもと、閲覧・API・MCP の利用を
サーバ側ログだけで数える。**出力に IP アドレスは含めない** (日別ユニーク数は
実行ごとの乱数ソルト付きハッシュで数え、ハッシュ自体も出力しない)。
生ログは既定でローカルに残さない (S3 から読み流す)。

使い方:
  .venv.nosync/bin/python scripts/access_stats.py --from 2026-09-01 --to 2026-09-30 \
      -o data/stats/2026-09            # → 2026-09.md / 2026-09.json
  .venv.nosync/bin/python scripts/access_stats.py --files logs/*.gz -o data/stats/x
  --bucket 省略時は CloudFormation スタック出力 AccessLogBucket を引く
  (AWS_PROFILE=AdministratorAccess-948645358251 が必要)。

集計の考え方 (URI の種別分けは classify_path、クライアント種別は classify_ua):
- 「レポートが実際に描画された」= ビューアがデータ JSON (r/{pair}/v/{版}.json)
  を fetch した回数 (render)。HTML だけ取って JS を動かさないクローラや
  エージェントはここに入らない
- report_entry (r/{pair}.html) / report_version / digest / events / mapping … は
  HTTP 200 のみ数える。人間の閲覧は client=browser に限る
- 流入元は Referer のホスト (自サイト除く)、AI エージェント・クローラ・
  プログラム (curl/python 等) は UA の既知トークンで分類 (KNOWN_AGENTS)
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import io
import json
import re
import secrets
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

SELF_HOSTS = {"diff.gtfs.jp", "d22mbbm5uatfcc.cloudfront.net"}
TOP_N = 30

# UA の既知トークン → (種別, 名前)。順序は「先に一致した方」なので特殊→一般
KNOWN_AGENTS: list[tuple[str, str, str]] = [
    # 自サーバー (MCP サーバーが台帳・成果物を CloudFront 経由で読む — mcp_tools.py)
    ("gtfs-semdiff-mcp", "internal", "mcp-server"),
    # AI エージェント (利用者の代理で取得) と AI クローラ (学習・索引)
    ("ChatGPT-User", "ai_agent", "ChatGPT-User"),
    ("OAI-SearchBot", "ai_agent", "OAI-SearchBot"),
    ("GPTBot", "ai_crawler", "GPTBot"),
    ("Claude-User", "ai_agent", "Claude-User"),
    ("Claude-SearchBot", "ai_agent", "Claude-SearchBot"),
    ("ClaudeBot", "ai_crawler", "ClaudeBot"),
    ("anthropic-ai", "ai_crawler", "anthropic-ai"),
    ("Perplexity-User", "ai_agent", "Perplexity-User"),
    ("PerplexityBot", "ai_crawler", "PerplexityBot"),
    ("Google-Extended", "ai_crawler", "Google-Extended"),
    ("GoogleAgent-Mariner", "ai_agent", "GoogleAgent-Mariner"),
    ("Gemini-Deep-Research", "ai_agent", "Gemini-Deep-Research"),
    ("MistralAI-User", "ai_agent", "MistralAI-User"),
    ("DuckAssistBot", "ai_agent", "DuckAssistBot"),
    ("Bytespider", "ai_crawler", "Bytespider"),
    ("CCBot", "ai_crawler", "CCBot"),
    ("cohere-ai", "ai_crawler", "cohere-ai"),
    ("meta-externalagent", "ai_crawler", "meta-externalagent"),
    ("Applebot-Extended", "ai_crawler", "Applebot-Extended"),
    ("Amazonbot", "ai_crawler", "Amazonbot"),
    ("YouBot", "ai_crawler", "YouBot"),
    # 検索クローラ
    ("Googlebot", "crawler", "Googlebot"),
    ("bingbot", "crawler", "bingbot"),
    ("Applebot", "crawler", "Applebot"),
    ("DuckDuckBot", "crawler", "DuckDuckBot"),
    ("YandexBot", "crawler", "YandexBot"),
    ("Baiduspider", "crawler", "Baiduspider"),
    ("AhrefsBot", "crawler", "AhrefsBot"),
    ("SemrushBot", "crawler", "SemrushBot"),
    ("MJ12bot", "crawler", "MJ12bot"),
    ("DotBot", "crawler", "DotBot"),
    ("PetalBot", "crawler", "PetalBot"),
    # SNS / チャットのリンクプレビュー
    ("Twitterbot", "preview", "Twitterbot"),
    ("facebookexternalhit", "preview", "facebook"),
    ("Slackbot", "preview", "Slackbot"),
    ("Discordbot", "preview", "Discordbot"),
    ("LinkedInBot", "preview", "LinkedInBot"),
    ("Line/", "preview", "LINE"),
    ("TelegramBot", "preview", "TelegramBot"),
    ("WhatsApp", "preview", "WhatsApp"),
    ("Mastodon", "preview", "Mastodon"),
    ("Bluesky", "preview", "Bluesky"),
    # プログラム (API / MCP クライアント / 手作業の curl 等)
    ("python-requests", "program", "python-requests"),
    ("python-httpx", "program", "python-httpx"),
    ("aiohttp", "program", "aiohttp"),
    ("curl/", "program", "curl"),
    ("Wget", "program", "wget"),
    ("Go-http-client", "program", "go-http"),
    ("node-fetch", "program", "node-fetch"),
    ("undici", "program", "undici"),
    ("axios", "program", "axios"),
    ("okhttp", "program", "okhttp"),
    ("Java/", "program", "java"),
    ("libwww-perl", "program", "perl"),
    ("Ruby", "program", "ruby"),
    ("PostmanRuntime", "program", "postman"),
    ("node", "program", "node"),
    ("Deno", "program", "deno"),
    ("Bun/", "program", "bun"),
]
_BROWSER_RE = re.compile(r"Mozilla/5\.0.*(Chrome|Safari|Firefox|Edg|OPR|Vivaldi|SamsungBrowser)")
_GENERIC_BOT_RE = re.compile(r"bot|crawler|spider|scraper|fetch|monitor|scan", re.I)

# キー規則は infra/runtime/versioning.py (pair は org__feed__uid__uid、版は CalVer)。
# 成果物の接尾辞: events / rawdiffs / digest(.en) / routes.digest / mapping
_KINDS = r"events|rawdiffs|digest|digest\.en|routes\.digest|mapping"
_VER = r"\d{4}\.\d{1,2}\.\d{1,2}\.\d+"
_PAIR = r"[^/.]+"  # pair に "." は含まれない (uid は hex 8 桁)
_RE_REPORT_ENTRY = re.compile(rf"^/r/(?P<pair>{_PAIR})\.html$")
_RE_ENTRY_ALIAS = re.compile(rf"^/r/(?P<pair>{_PAIR})\.(?P<kind>{_KINDS})\.(?:json|md)$")
_RE_REPORT_VERSION = re.compile(rf"^/r/(?P<pair>{_PAIR})/v/(?P<ver>{_VER})\.html$")
_RE_VIEWER_DATA = re.compile(rf"^/r/(?P<pair>{_PAIR})/v/(?P<ver>{_VER})\.json$")
_RE_LEDGER = re.compile(rf"^/r/(?P<pair>{_PAIR})/index\.json$")
_RE_ARTIFACT = re.compile(
    rf"^/r/(?P<pair>{_PAIR})/v/(?P<ver>{_VER})\.(?P<kind>{_KINDS})\.(?:json|md)$")
# アップロード由来 (r/u/{id} 恒久、r/anon/{id} 30 日): id は "u-xxxx" 等
_RE_UPLOAD = re.compile(
    rf"^/r/(?P<scope>u|anon)/(?P<id>[^/.]+)(?:\.(?P<kind>{_KINDS}))?\.(?P<ext>html|json|md)$")
_STATIC = {"/": "top", "/index.html": "top", "/developers.html": "developers",
           "/terms.html": "terms", "/admin.html": "admin", "/llms.txt": "llms",
           "/robots.txt": "robots"}


def _kind_name(suffix: str) -> str:
    """接尾辞 → 種別名 (digest.en は digest に併合、routes.digest は routes_digest)。"""
    return suffix.replace(".en", "").replace(".", "_")


def classify_path(path: str) -> tuple[str, str]:
    """URI → (種別, 対象)。対象はレポートなら pair、それ以外は空か補助情報。"""
    if path in _STATIC:
        return _STATIC[path], ""
    if path == "/mcp":
        return "mcp", ""
    if path.startswith("/api/"):
        # /api/jobs/{id} → /api/jobs/{id} に丸める (ID は集計対象外)
        parts = path.split("/")
        if len(parts) >= 4 and parts[2] in ("jobs",):
            return "api", f"/api/{parts[2]}/{{id}}"
        return "api", path
    if path.startswith("/docs/"):
        return "docs", path
    if path.startswith("/feeds/") and path.endswith(".json"):
        return "feed_ledger", path[len("/feeds/"):-len(".json")]  # versioning.feed_ledger_key
    if (m := _RE_VIEWER_DATA.match(path)):
        return "render", m["pair"]
    if (m := _RE_REPORT_ENTRY.match(path)):
        return "report_entry", m["pair"]
    if (m := _RE_ENTRY_ALIAS.match(path)):
        return _kind_name(m["kind"]), m["pair"]
    if (m := _RE_REPORT_VERSION.match(path)):
        return "report_version", m["pair"]
    if (m := _RE_LEDGER.match(path)):
        return "ledger", m["pair"]
    if (m := _RE_ARTIFACT.match(path)):
        return _kind_name(m["kind"]), m["pair"]
    if (m := _RE_UPLOAD.match(path)):
        kind, ext = m["kind"], m["ext"]
        target = f"(upload:{m['scope']})"
        if kind:
            return _kind_name(kind), target
        return ("report_entry" if ext == "html" else "render"), target
    if path.startswith("/r/"):
        return "report_other", ""
    if re.search(r"\.(png|ico|svg|css|js|woff2?|webmanifest)$", path):
        return "asset", ""
    return "other", ""


def classify_ua(ua: str) -> tuple[str, str]:
    """User-Agent → (種別, 名前)。種別: browser / ai_agent / ai_crawler / crawler /
    preview / program / internal (自サーバー) / bot / other。"""
    if not ua or ua == "-":
        return "other", ""
    for token, kind, name in KNOWN_AGENTS:
        if token in ua:
            return kind, name
    if _BROWSER_RE.search(ua):
        return "browser", ""
    if _GENERIC_BOT_RE.search(ua):
        return "bot", ua.split("/")[0][:40]
    return "other", ua.split("/")[0][:40]


def referrer_host(ref: str) -> str:
    if not ref or ref == "-":
        return ""
    try:
        host = urllib.parse.urlsplit(ref).hostname or ""
    except ValueError:
        return ""
    return "" if host in SELF_HOSTS else host.lower()


def parse_log(text: str):
    """W3C 拡張形式 (CloudFront 標準ログ) を dict の列にする。#Fields 行で列名を取る。"""
    fields: list[str] = []
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith("#Fields:"):
            fields = line[len("#Fields:"):].split()
            continue
        if line.startswith("#"):
            continue
        cols = line.split("\t")
        if not fields or len(cols) < len(fields):
            continue
        rec = dict(zip(fields, cols))
        for k in ("cs(User-Agent)", "cs(Referer)", "cs-uri-stem"):
            if k in rec:
                rec[k] = urllib.parse.unquote(rec[k])
        yield rec


class Stats:
    """集計器。add() に parse_log のレコードを流し込み、result() で dict を返す。"""

    def __init__(self) -> None:
        self._salt = secrets.token_bytes(16)  # 実行ごとに捨てる (再識別不能)
        self.total = 0
        self.status = collections.Counter()
        self.by_day = collections.defaultdict(lambda: {"requests": 0, "renders": 0,
                                                       "visitors": set(), "mcp": 0, "api": 0})
        self.kinds = collections.Counter()          # 種別 (200 のみ)
        self.kinds_human = collections.Counter()    # 種別 (200・browser のみ)
        self.reports = collections.defaultdict(collections.Counter)  # pair → 種別
        self.referrers = collections.Counter()      # host (browser の HTML/render のみ)
        self.clients = collections.Counter()        # (種別, 名前)
        self.client_kinds_by_kind = collections.defaultdict(collections.Counter)
        self.edges = collections.Counter()
        self.api_paths = collections.Counter()
        self.bytes = 0

    def add(self, r: dict) -> None:
        self.total += 1
        day = r.get("date", "")
        status = r.get("sc-status", "")
        self.status[status] += 1
        path = r.get("cs-uri-stem", "")
        method = r.get("cs-method", "")
        kind, target = classify_path(path)
        ckind, cname = classify_ua(r.get("cs(User-Agent)", ""))
        self.bytes += int(r.get("sc-bytes") or 0)
        d = self.by_day[day]
        d["requests"] += 1
        self.edges[(r.get("x-edge-location") or "")[:3]] += 1
        self.clients[(ckind, cname)] += 1
        if kind == "mcp" and method == "POST":
            d["mcp"] += 1
        if kind == "api":
            d["api"] += 1
            self.api_paths[f"{method} {target}"] += 1
        if not status.startswith("2"):
            return
        self.kinds[kind] += 1
        self.client_kinds_by_kind[kind][ckind] += 1
        if kind == "render":
            d["renders"] += 1
        if target and kind in ("render", "report_entry", "report_version", "digest",
                               "events", "mapping", "routes_digest", "rawdiffs", "ledger"):
            self.reports[target][kind] += 1
        if ckind == "browser":
            self.kinds_human[kind] += 1
            if kind in ("top", "report_entry", "report_version", "developers", "terms"):
                h = hashlib.sha256(self._salt + (r.get("c-ip", "") + "|" +
                                                 r.get("cs(User-Agent)", "")).encode()
                                   ).hexdigest()[:16]
                d["visitors"].add(h)
                host = referrer_host(r.get("cs(Referer)", ""))
                if host:
                    self.referrers[host] += 1

    def result(self) -> dict:
        days = {k: {"requests": v["requests"], "renders": v["renders"],
                    "visitors": len(v["visitors"]), "mcp": v["mcp"], "api": v["api"]}
                for k, v in sorted(self.by_day.items())}
        reports = sorted(self.reports.items(),
                         key=lambda kv: (-kv[1]["render"], -kv[1]["report_entry"], kv[0]))
        return {
            "total_requests": self.total,
            "bytes_served": self.bytes,
            "status": dict(self.status.most_common()),
            "days": days,
            "kinds_200": dict(self.kinds.most_common()),
            "kinds_200_browser": dict(self.kinds_human.most_common()),
            "reports": [{"pair": p, **dict(c)} for p, c in reports[:TOP_N]],
            "reports_total": len(self.reports),
            "referrers": dict(self.referrers.most_common(TOP_N)),
            "clients": [{"kind": k, "name": n, "requests": c}
                        for (k, n), c in self.clients.most_common(TOP_N)],
            "client_kinds_by_page_kind": {k: dict(v.most_common())
                                          for k, v in self.client_kinds_by_kind.items()},
            "api_paths": dict(self.api_paths.most_common(TOP_N)),
            "edges": dict(self.edges.most_common(15)),
        }


def render_markdown(res: dict, title: str) -> str:
    L = [f"# アクセス集計: {title}", "",
         f"- 総リクエスト: {res['total_requests']:,} / 配信バイト: "
         f"{res['bytes_served'] / 1e6:,.1f} MB",
         "- ステータス: " + ", ".join(f"{k}: {v:,}" for k, v in res["status"].items()),
         "", "## 日別 (visitors = ブラウザでの閲覧者の概数、renders = レポート描画数)", "",
         "| 日付 | requests | renders | visitors | api | mcp |", "|---|---:|---:|---:|---:|---:|"]
    for d, v in res["days"].items():
        L.append(f"| {d} | {v['requests']:,} | {v['renders']:,} | {v['visitors']:,} "
                 f"| {v['api']:,} | {v['mcp']:,} |")
    L += ["", "## ページ種別 (HTTP 2xx)", "", "| 種別 | 全クライアント | ブラウザのみ |",
          "|---|---:|---:|"]
    for k, v in res["kinds_200"].items():
        L.append(f"| {k} | {v:,} | {res['kinds_200_browser'].get(k, 0):,} |")
    L += ["", f"## レポート別 (上位 {TOP_N} / 全 {res['reports_total']:,} ペア)", "",
          "| pair | render | entry | version | digest | events | mapping |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for r in res["reports"]:
        L.append(f"| {r['pair']} | {r.get('render', 0)} | {r.get('report_entry', 0)} "
                 f"| {r.get('report_version', 0)} | {r.get('digest', 0)} "
                 f"| {r.get('events', 0)} | {r.get('mapping', 0)} |")
    L += ["", "## 流入元 (ブラウザ閲覧の Referer ホスト、自サイト除く)", ""]
    L += [f"- {h}: {c:,}" for h, c in res["referrers"].items()] or ["- (なし)"]
    L += ["", "## クライアント種別", "", "| 種別 | 名前 | requests |", "|---|---|---:|"]
    for c in res["clients"]:
        L.append(f"| {c['kind']} | {c['name'] or '-'} | {c['requests']:,} |")
    L += ["", "## API パス", ""]
    L += [f"- {p}: {c:,}" for p, c in res["api_paths"].items()] or ["- (なし)"]
    L += ["", "## エッジ (IATA 3 文字、地域の目安)", "",
          ", ".join(f"{k}: {v:,}" for k, v in res["edges"].items()), ""]
    return "\n".join(L)


# --- 入力 ---

def iter_local_files(paths: list[str]):
    for p in paths:
        raw = Path(p).read_bytes()
        yield gzip.decompress(raw).decode("utf-8") if raw[:2] == b"\x1f\x8b" \
            else raw.decode("utf-8")


def iter_s3_logs(bucket: str, prefix: str, start: date, end: date, profile: str | None):
    """S3 上のログ (cloudfront/{distribution}.{YYYY-MM-DD}-{HH}.{id}.gz) を
    日付範囲で読み流す。ローカルには残さない。"""
    import boto3  # 集計時のみ必要 (dev extra には入れない)

    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client("s3")
    day_re = re.compile(r"\.(\d{4}-\d{2}-\d{2})-\d{2}\.")
    paginator = s3.get_paginator("list_objects_v2")
    n = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            m = day_re.search(obj["Key"])
            if not m:
                continue
            d = date.fromisoformat(m.group(1))
            if d < start or d > end:
                continue
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            n += 1
            yield gzip.GzipFile(fileobj=io.BytesIO(body)).read().decode("utf-8")
    print(f"読み込んだログファイル: {n}", file=sys.stderr)


def discover_bucket(profile: str | None) -> str:
    import boto3

    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    cfn = session.client("cloudformation")
    outs = cfn.describe_stacks(StackName="GtfsSemdiffDelivery")["Stacks"][0]["Outputs"]
    for o in outs:
        if o["OutputKey"] == "AccessLogBucket":
            return o["OutputValue"]
    raise SystemExit("スタック出力 AccessLogBucket が見つからない (デプロイ済みか?)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="start", help="YYYY-MM-DD (既定: 30 日前)")
    ap.add_argument("--to", dest="end", help="YYYY-MM-DD (既定: 今日)")
    ap.add_argument("--bucket", help="ログバケット (既定: スタック出力から)")
    ap.add_argument("--prefix", default="cloudfront/")
    ap.add_argument("--profile", default="AdministratorAccess-948645358251")
    ap.add_argument("--files", nargs="*", help="S3 でなくローカルのログファイル (gz 可)")
    ap.add_argument("-o", "--output", required=True, help="出力の基底パス (.md/.json を付ける)")
    a = ap.parse_args(argv)

    stats = Stats()
    if a.files:
        texts = iter_local_files(a.files)
        title = f"{len(a.files)} ファイル"
    else:
        end = date.fromisoformat(a.end) if a.end else datetime.now().date()
        start = date.fromisoformat(a.start) if a.start else end - timedelta(days=30)
        bucket = a.bucket or discover_bucket(a.profile)
        texts = iter_s3_logs(bucket, a.prefix, start, end, a.profile)
        title = f"{start} 〜 {end}"
    for text in texts:
        for rec in parse_log(text):
            stats.add(rec)
    res = stats.result()
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(res, title), encoding="utf-8")
    print(f"{out.with_suffix('.md')} / {out.with_suffix('.json')}: "
          f"{res['total_requests']:,} requests", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
