"""gtfs-data.jp API v2 クライアント (旧 GTFSDiff repository.py の移植 + キャッシュ追加)。

API 仕様 (2026-07 動作確認済み, CLAUDE.md 参照):
- GET /feeds?pref=<id> / /feeds?org_id=<id>      フィード一覧 (body: list)
- GET /organizations/{org}/feeds/{feed}?max_prev=N  世代付きファイル一覧
  (body.gtfs_files: [{gtfs_file_uid, rid, gtfs_url, from_date, to_date,
   published_at, memo}, ...]。body 直下に feed_license 等のフィード情報)
- RID 体系: current, prev_1, prev_2, ... (相対 ID。世代が進むとずれる)
- gtfs_file_uid: 世代の恒久 UUID。gtfs_url も uid ベースで rid 非依存 (W3-2a から
  記録・同定はこちらを正とする)

ダウンロードは cache_dir (config: repository.cache_dir) にキャッシュする。
rid は世代が進むとずれる (current → prev_1) ため、キャッシュキーには
rid を使わず有効期間 + URL ハッシュを使う。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from ..config import Config
from ..model import SnapshotMeta

logger = logging.getLogger(__name__)

USER_AGENT = "gtfs-semantic-diff/0.1"


class RepositoryError(RuntimeError):
    """gtfs-data.jp API との通信・応答解釈の失敗。"""


@dataclass(frozen=True)
class FeedInfo:
    feed_id: str
    name: str
    org_id: str
    org_name: str = ""
    is_active: bool = True
    last_updated_at: str = ""
    memo: str = ""


@dataclass(frozen=True)
class GtfsFileInfo:
    org_id: str
    feed_id: str
    rid: str  # current, prev_1, ... (取得時点の相対 ID)
    download_url: str
    uid: str = ""  # gtfs_file_uid (恒久 UUID)
    from_date: str = ""
    to_date: str = ""
    published_at: str = ""
    feed_license: str = ""  # フィード単位の値を世代ごとに複製して保持
    memo: str = ""

    def snapshot_meta(self, local_path: Path | None = None) -> SnapshotMeta:
        return SnapshotMeta(
            source=str(local_path) if local_path else self.download_url,
            org_id=self.org_id,
            feed_id=self.feed_id,
            rid=self.rid,
            uid=self.uid,
            from_date=self.from_date,
            to_date=self.to_date,
            published_at=self.published_at,
            feed_license=self.feed_license,
        )


@dataclass(frozen=True)
class FetchedFeed:
    """ダウンロード済み世代1つ。path はローカル zip。"""

    info: GtfsFileInfo
    path: Path
    from_cache: bool


def rid_order(rid: str) -> int:
    """RID の新しさ順序。小さいほど新しい (next_n < current=0 < prev_n)。"""
    if rid == "current":
        return 0
    prefix, _, num = rid.partition("_")
    try:
        n = int(num)
    except ValueError:
        return 10**6  # 解釈不能な rid は最古扱い
    if prefix == "prev":
        return n
    if prefix == "next":
        return -n
    return 10**6


class GtfsDataRepository:
    """gtfs-data.jp API v2 クライアント。session 注入でテスト時にモック可能。"""

    def __init__(self, config: Config | None = None, session: requests.Session | None = None):
        self.config = config or Config.load()
        self.base_url = self.config.repository_base_url.rstrip("/")
        self.cache_dir = self.config.cache_dir
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})

    # --- API ---

    def _get_json(self, url: str, params: dict | None = None) -> dict | list:
        try:
            resp = self.session.get(url, params=params, timeout=60)
        except requests.RequestException as e:
            raise RepositoryError(f"API 接続失敗: {url}: {e}") from e
        if resp.status_code == 404:
            raise RepositoryError(f"見つかりません (404): {url}")
        if resp.status_code != 200:
            raise RepositoryError(
                f"API エラー {resp.status_code}: {url}: {resp.text[:200]}"
            )
        return resp.json()

    def list_feeds(self, org_id: str | None = None, pref: int | None = None) -> list[FeedInfo]:
        params: dict = {}
        if org_id:
            params["org_id"] = org_id
        if pref is not None:
            params["pref"] = pref
        data = self._get_json(f"{self.base_url}/feeds", params)
        body = data.get("body", data) if isinstance(data, dict) else data
        if isinstance(body, dict):
            body = [body]
        feeds = []
        for fd in body or []:
            feeds.append(
                FeedInfo(
                    feed_id=fd.get("feed_id", ""),
                    name=fd.get("feed_name", ""),
                    org_id=fd.get("organization_id", org_id or ""),
                    org_name=fd.get("organization_name", ""),
                    is_active=not fd.get("feed_is_discontinued", False),
                    last_updated_at=fd.get("last_updated_at", ""),
                    memo=fd.get("feed_memo", ""),
                )
            )
        return feeds

    def get_feed_files(self, org_id: str, feed_id: str, max_prev: int = 9) -> list[GtfsFileInfo]:
        url = f"{self.base_url}/organizations/{org_id}/feeds/{feed_id}"
        data = self._get_json(url, {"max_prev": max_prev})
        body = data.get("body", {}) if isinstance(data, dict) else {}
        gtfs_files = body.get("gtfs_files", [])
        if not gtfs_files:
            raise RepositoryError(f"世代ファイルが見つかりません: {org_id}/{feed_id}")
        feed_license = body.get("feed_license", "")
        return [
            GtfsFileInfo(
                org_id=org_id,
                feed_id=feed_id,
                rid=gf.get("rid", ""),
                download_url=gf.get("gtfs_url", ""),
                uid=gf.get("gtfs_file_uid", ""),
                from_date=gf.get("from_date", ""),
                to_date=gf.get("to_date", ""),
                published_at=gf.get("published_at", ""),
                feed_license=feed_license,
                memo=gf.get("memo", ""),
            )
            for gf in gtfs_files
        ]

    # --- キャッシュ付きダウンロード ---

    def _cache_path(self, info: GtfsFileInfo) -> Path:
        url_hash = hashlib.sha256(info.download_url.encode()).hexdigest()[:10]
        stem = f"{info.from_date or 'nodate'}_{url_hash}"
        return self.cache_dir / info.org_id / info.feed_id / f"{stem}.zip"

    def download(self, info: GtfsFileInfo, force: bool = False) -> FetchedFeed:
        """世代 zip をキャッシュへダウンロードする。既存なら再取得しない。"""
        target = self._cache_path(info)
        if target.exists() and target.stat().st_size > 0 and not force:
            logger.info("キャッシュ命中: %s (%s)", target.name, info.rid)
            return FetchedFeed(info=info, path=target, from_cache=True)

        if not info.download_url:
            raise RepositoryError(f"ダウンロード URL がありません: {info}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".zip.part")
        logger.info("ダウンロード: %s (%s)", info.download_url, info.rid)
        try:
            with self.session.get(info.download_url, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
            tmp.replace(target)
        except requests.RequestException as e:
            tmp.unlink(missing_ok=True)
            raise RepositoryError(f"ダウンロード失敗 ({info.rid}): {e}") from e

        # 出自メタデータを隣に残す (キャッシュファイル名からは rid が読めないため)
        meta_path = target.with_suffix(".json")
        meta_path.write_text(
            json.dumps(asdict(info), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return FetchedFeed(info=info, path=target, from_cache=False)

    def fetch_generations(
        self, org_id: str, feed_id: str, rids: tuple[str, ...] = ("prev_1", "current")
    ) -> list[FetchedFeed]:
        """指定 rid の世代 zip 群を (古い順の指定どおり) 取得する。"""
        max_prev = max(
            (int(r.split("_")[1]) for r in rids if r.startswith("prev_")), default=1
        )
        files = {f.rid: f for f in self.get_feed_files(org_id, feed_id, max_prev=max_prev)}
        fetched = []
        for rid in rids:
            if rid not in files:
                available = sorted(files.keys())
                raise RepositoryError(
                    f"rid '{rid}' がありません: {org_id}/{feed_id} (利用可能: {available})"
                )
            fetched.append(self.download(files[rid]))
        return fetched
