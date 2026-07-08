"""GTFS 読み込み・正規化と gtfs-data.jp API クライアント (旧 core.py / repository.py を移植)."""

from .loader import REQUIRED_FILES, GtfsLoadError, load_snapshot
from .repository import (
    FeedInfo,
    FetchedFeed,
    GtfsDataRepository,
    GtfsFileInfo,
    RepositoryError,
)

__all__ = [
    "REQUIRED_FILES",
    "GtfsLoadError",
    "load_snapshot",
    "FeedInfo",
    "FetchedFeed",
    "GtfsDataRepository",
    "GtfsFileInfo",
    "RepositoryError",
]
