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
