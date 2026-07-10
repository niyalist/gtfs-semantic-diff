"""load/repository.py の単体テスト (API はモック、ネットワーク非依存)。"""

import json
from pathlib import Path

import pytest

from gtfs_semantic_diff.config import Config
from gtfs_semantic_diff.load import GtfsDataRepository, RepositoryError

from .conftest import make_gtfs_zip

BASE = "https://api.gtfs-data.jp/v2"

FEEDS_RESPONSE = {
    "body": [
        {
            "feed_id": "Nagaibus",
            "feed_name": "永井運輸バス",
            "organization_id": "nagai-unyu",
            "organization_name": "永井運輸",
            "feed_is_discontinued": False,
            "last_updated_at": "2026-06-01",
            "feed_memo": "",
        }
    ]
}


def files_response(zip_url_current: str, zip_url_prev: str) -> dict:
    return {
        "body": {
            "feed_license": "CC BY 4.0",
            "gtfs_files": [
                {
                    "gtfs_file_uid": "17ab34e1-dcb8-4b2e-9cda-ae2b68f4c444",
                    "rid": "current",
                    "gtfs_url": zip_url_current,
                    "from_date": "2026-04-01",
                    "to_date": "2027-03-31",
                    "published_at": "2026-07-08T18:09:26+09:00",
                    "memo": "",
                },
                {
                    "gtfs_file_uid": "b1be1add-3553-4b31-86bc-348479c25526",
                    "rid": "prev_1",
                    "gtfs_url": zip_url_prev,
                    "from_date": "2025-10-01",
                    "to_date": "2026-03-31",
                    "published_at": "2025-09-26T06:23:03+09:00",
                    "memo": "",
                },
            ],
        }
    }


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self._content = content
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code != 200:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """URL → FakeResponse のルーティングと呼び出し記録。"""

    def __init__(self, routes: dict):
        self.routes = routes
        self.headers = {}
        self.calls: list[str] = []

    def get(self, url, params=None, stream=False, timeout=None):
        self.calls.append(url)
        if url not in self.routes:
            return FakeResponse(status_code=404)
        return self.routes[url]


@pytest.fixture
def repo_setup(tmp_path):
    """モック API + tmp キャッシュディレクトリの GtfsDataRepository を作る。"""
    zip_bytes = make_gtfs_zip(tmp_path, name="src.zip").read_bytes()
    cur_url = "https://example.com/current.zip"
    prev_url = "https://example.com/prev1.zip"
    session = FakeSession(
        {
            f"{BASE}/feeds": FakeResponse(json_data=FEEDS_RESPONSE),
            f"{BASE}/organizations/nagai-unyu/feeds/Nagaibus": FakeResponse(
                json_data=files_response(cur_url, prev_url)
            ),
            cur_url: FakeResponse(content=zip_bytes),
            prev_url: FakeResponse(content=zip_bytes),
        }
    )
    config = Config(
        raw={"repository": {"base_url": BASE, "cache_dir": str(tmp_path / "cache")}},
        source_path=Path("(test)"),
    )
    return GtfsDataRepository(config=config, session=session), session


def test_list_feeds(repo_setup):
    repo, _ = repo_setup
    feeds = repo.list_feeds(org_id="nagai-unyu")
    assert len(feeds) == 1
    assert feeds[0].feed_id == "Nagaibus"
    assert feeds[0].is_active


def test_get_feed_files(repo_setup):
    repo, _ = repo_setup
    files = repo.get_feed_files("nagai-unyu", "Nagaibus")
    assert [f.rid for f in files] == ["current", "prev_1"]
    assert files[0].from_date == "2026-04-01"


def test_get_feed_files_uid_and_license(repo_setup):
    """W3-2a: 世代恒久 UUID とライセンスを保持し、SnapshotMeta まで流れる。"""
    repo, _ = repo_setup
    files = repo.get_feed_files("nagai-unyu", "Nagaibus")
    assert files[0].uid == "17ab34e1-dcb8-4b2e-9cda-ae2b68f4c444"
    assert files[1].uid == "b1be1add-3553-4b31-86bc-348479c25526"
    assert all(f.feed_license == "CC BY 4.0" for f in files)
    meta = files[0].snapshot_meta()
    assert meta.uid == files[0].uid
    assert meta.published_at == "2026-07-08T18:09:26+09:00"
    assert meta.feed_license == "CC BY 4.0"


def test_fetch_generations_downloads_and_caches(repo_setup):
    repo, session = repo_setup
    fetched = repo.fetch_generations("nagai-unyu", "Nagaibus")
    assert [f.info.rid for f in fetched] == ["prev_1", "current"]
    assert all(f.path.exists() and f.path.stat().st_size > 0 for f in fetched)
    assert all(not f.from_cache for f in fetched)
    # 出自メタデータが隣に書かれている
    meta = json.loads(fetched[0].path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["rid"] == "prev_1"

    # 2回目はキャッシュ命中し、zip の再ダウンロードが発生しない
    downloads_before = sum(c.startswith("https://example.com/") for c in session.calls)
    fetched2 = repo.fetch_generations("nagai-unyu", "Nagaibus")
    downloads_after = sum(c.startswith("https://example.com/") for c in session.calls)
    assert all(f.from_cache for f in fetched2)
    assert downloads_before == downloads_after


def test_fetched_zip_loads_as_snapshot(repo_setup):
    from gtfs_semantic_diff.load import load_snapshot

    repo, _ = repo_setup
    fetched = repo.fetch_generations("nagai-unyu", "Nagaibus")
    for f in fetched:
        snapshot = load_snapshot(f.path, meta=f.info.snapshot_meta(f.path))
        assert snapshot.row_counts()["trips"] == 2
        assert snapshot.meta.rid == f.info.rid


def test_unknown_rid_raises(repo_setup):
    repo, _ = repo_setup
    with pytest.raises(RepositoryError, match="prev_9"):
        repo.fetch_generations("nagai-unyu", "Nagaibus", rids=("prev_9", "current"))


def test_unknown_feed_raises(repo_setup):
    repo, _ = repo_setup
    with pytest.raises(RepositoryError, match="404"):
        repo.get_feed_files("nagai-unyu", "NoSuchFeed")
