"""W3-2a: 正準 URL と版管理の純ロジック (設計: docs/design/web.md「W3-2 詳細方針」)。

boto3 に依存しない (ローカルの pytest で直接テストする。tests/test_web_versioning.py)。

- リポジトリ由来の結果は世代恒久 UUID (gtfs_file_uid) ベースの正準キーに置く。
  同一世代ペアは誰が実行しても同一 URL (実質公開・キャッシュ)。
- 生成済み結果は不変: r/{pair}/v/{YYYY.M.D.N}.html に版として追記し、
  入口 r/{pair}.html は最新版のコピー。index.json が版台帳。
"""

from __future__ import annotations

import re

UID_RE = re.compile(r"[0-9a-fA-F][0-9a-fA-F-]{7,63}")

# 正準キーに使う uid 先頭桁数。同一フィードの世代間 (数十個) での衝突を
# 避けられれば十分 (org/feed がキーに含まれるためフィード間衝突は無関係)
UID_PREFIX_LEN = 8


def safe_uid(value: str) -> str:
    """gtfs_file_uid の妥当性検査 (S3 キー・URL に安全な文字のみ)。"""
    if not value or not UID_RE.fullmatch(value):
        raise ValueError(f"invalid uid: {value!r}")
    return value


def uid_prefix(uid: str) -> str:
    return safe_uid(uid).replace("-", "")[:UID_PREFIX_LEN].lower()


def pair_id(org: str, feed: str, old_uid: str, new_uid: str) -> str:
    """世代ペアの正準 ID。r/{pair_id}.html が入口 URL になる。"""
    return f"{org}__{feed}__{uid_prefix(old_uid)}__{uid_prefix(new_uid)}"


def entry_key(pair: str) -> str:
    return f"r/{pair}.html"


def version_key(pair: str, version: str) -> str:
    return f"r/{pair}/v/{version}.html"


def data_key(pair: str, version: str) -> str:
    """版データ JSON (RD1b)。版 HTML と同じく不変。"""
    return f"r/{pair}/v/{version}.json"


def events_key(pair: str, version: str) -> str:
    """生データ DL: ChangeEventSet JSON (RD2)。不変。"""
    return f"r/{pair}/v/{version}.events.json"


def entry_digest_md_key(pair: str) -> str:
    """最新版ダイジェストの入口エイリアス (RD4b 追補)。
    「r/{pair}.html の .html を .digest.md に変えるだけ」の規則。"""
    return f"r/{pair}.digest.md"


def entry_digest_json_key(pair: str) -> str:
    return f"r/{pair}.digest.json"


def digest_md_key(pair: str, version: str) -> str:
    """AI 向けダイジェスト Markdown (RD4b)。版と並置・不変。"""
    return f"r/{pair}/v/{version}.digest.md"


def digest_json_key(pair: str, version: str) -> str:
    """AI 向けダイジェスト JSON (RD4b)。版と並置・不変。"""
    return f"r/{pair}/v/{version}.digest.json"


def routes_digest_key(pair: str, version: str) -> str:
    """全路線 L1 (routes.digest.json、RD4c-0)。gzip 配信・不変。"""
    return f"r/{pair}/v/{version}.routes.digest.json"


def mapping_key(pair: str, version: str) -> str:
    """ID 対応表 (mapping.json、IM1)。gzip 配信・不変。"""
    return f"r/{pair}/v/{version}.mapping.json"


def entry_alias_keys(pair: str) -> dict[str, str]:
    """最新版エイリアス一式 (r/{pair}.{suffix})。suffix は成果物名と対応。"""
    return {
        "digest_md": f"r/{pair}.digest.md",
        "digest_json": f"r/{pair}.digest.json",
        "routes_digest": f"r/{pair}.routes.digest.json",
        "mapping": f"r/{pair}.mapping.json",
    }


def artifacts_of(pair: str, version: str) -> dict[str, dict]:
    """版のマニフェスト (成果物名 → url・配信属性)。index.json に載せ、
    URL 規則を「知識」でなく「データ」にする (ai_interface.md §5.2)。"""
    return {
        "html": {"url": "/" + version_key(pair, version)},
        "viewer_data": {"url": "/" + data_key(pair, version), "gzip": True,
                        "stable": False},
        "events": {"url": "/" + events_key(pair, version), "gzip": True},
        "rawdiffs": {"url": "/" + rawdiffs_key(pair, version), "gzip": True},
        "digest_md": {"url": "/" + digest_md_key(pair, version), "schema": 1},
        "digest_json": {"url": "/" + digest_json_key(pair, version), "schema": 1},
        "routes_digest": {"url": "/" + routes_digest_key(pair, version),
                          "gzip": True, "schema": 1},
        "mapping": {"url": "/" + mapping_key(pair, version),
                    "gzip": True, "schema": 1},
    }


def feed_ledger_key(org: str, feed: str) -> str:
    """フィード台帳 (このフィードで計算済みのペア一覧)。ai_interface.md §5.2。
    org/feed はジョブ受付時に _safe_id 検査済みの値を渡すこと。"""
    return f"feeds/{org}__{feed}.json"


def update_feed_ledger(ledger: dict | None, *, org: str, feed: str,
                       pair: str, feed_info: dict, version: str,
                       updated_at: str) -> dict:
    """フィード台帳にペアを追記 (同ペアは置き換え = 冪等)。
    並びは (new_from_date, old_from_date) — 隣接世代の連鎖が読み取れる順。"""
    entry = {
        "pair": pair,
        "old_uid": feed_info.get("old_uid", ""),
        "new_uid": feed_info.get("new_uid", ""),
        "old_from_date": feed_info.get("old_from_date", ""),
        "new_from_date": feed_info.get("new_from_date", ""),
        "latest_version": version,
        "report": f"/{entry_key(pair)}",
        "index": f"/{index_key(pair)}",
        "updated_at": updated_at,
    }
    pairs = [p for p in (ledger or {}).get("pairs", []) if p.get("pair") != pair]
    pairs.append(entry)
    pairs.sort(key=lambda p: (p.get("new_from_date", ""),
                              p.get("old_from_date", ""), p.get("pair", "")))
    return {"org": org, "feed": feed, "pairs": pairs, "updated_at": updated_at}


def rawdiffs_key(pair: str, version: str) -> str:
    """生データ DL: RawDiff 全件 JSON (RD2)。不変。"""
    return f"r/{pair}/v/{version}.rawdiffs.json"


def index_key(pair: str) -> str:
    return f"r/{pair}/index.json"


def parse_version(version: str) -> tuple[int, ...]:
    """CalVer 'YYYY.M.D.N' を比較可能なタプルへ。旧3要素形式は N=0 として扱う。

    解釈不能な要素は 0 (最古扱い) — 比較で落ちないことを優先する。
    """
    parts = []
    for p in version.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def update_index(
    index: dict | None,
    *,
    pair: str,
    version: str,
    generated_at: str,
    feed_info: dict | None = None,
) -> dict:
    """版台帳 (index.json) に version を追記した新しい dict を返す。

    - 同じ version が既にあれば置き換える (再実行は冪等)
    - versions は新しい版が先頭 (parse_version 降順)
    - latest は最大版 (追記順に依存しない)
    """
    entry = {
        "version": version,
        "generated_at": generated_at,
        "key": version_key(pair, version),
        # RD4b 追補 (互換のため残置。正式なマニフェストは artifacts)
        "digest_md": digest_md_key(pair, version),
        "digest_json": digest_json_key(pair, version),
        # RD4c-0: 版のマニフェスト。URL 規則の暗記を不要にする
        "artifacts": artifacts_of(pair, version),
    }
    versions = [
        v for v in (index or {}).get("versions", []) if v.get("version") != version
    ]
    versions.append(entry)
    versions.sort(key=lambda v: parse_version(v.get("version", "")), reverse=True)
    out = {
        "pair": pair,
        "versions": versions,
        "latest": versions[0]["version"],
    }
    if feed_info:
        out["feed"] = feed_info
    elif index and "feed" in index:
        out["feed"] = index["feed"]
    return out


def latest_version(index: dict | None) -> str | None:
    if not index or not index.get("versions"):
        return None
    return index.get("latest")
