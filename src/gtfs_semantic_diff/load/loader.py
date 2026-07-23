"""GTFS zip / ディレクトリ → GtfsSnapshot の読み込み・正規化。

方針:
- zip 内の *.txt を **全て** 読む (既知ファイル限定にしない)。L0 網羅 diff の前提。
- 全列 str dtype、欠損は空文字列 "" に統一 (keep_default_na=False)。
- 文字コードは UTF-8 (BOM 可) を試し、失敗したら cp932 にフォールバック。
- zip 直下に .txt がなく単一フォルダに入っているケース (実フィードに存在) も吸収。
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import pandas as pd

from ..config import Config
from ..model import GtfsSnapshot, SnapshotMeta
from .day_types import normalize_day_types

logger = logging.getLogger(__name__)

REQUIRED_FILES = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}


class GtfsLoadError(ValueError):
    """GTFS として読めない入力 (必須ファイル欠落など)。"""


def _read_csv_bytes(data: bytes, name: str) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "cp932"):
        try:
            df = pd.read_csv(
                io.BytesIO(data),
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
                skip_blank_lines=True,
            )
            if encoding != "utf-8-sig":
                logger.info("%s: %s として読み込みました", name, encoding)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except UnicodeDecodeError:
            continue
    raise GtfsLoadError(f"{name}: UTF-8 / cp932 のいずれでも読み込めません")


def _collect_txt_from_zip(path: Path) -> dict[str, bytes]:
    """zip から .txt ファイル名 → バイト列を集める。直下優先、なければ1階層下。"""
    with zipfile.ZipFile(path) as zf:
        entries = [n for n in zf.namelist() if n.endswith(".txt") and not n.startswith("__MACOSX")]
        root_entries = [n for n in entries if "/" not in n]
        if not root_entries:
            # 単一フォルダ格納パターン: 深さ1のエントリのみ採用
            root_entries = [n for n in entries if n.count("/") == 1]
        files: dict[str, bytes] = {}
        for name in root_entries:
            basename = name.rsplit("/", 1)[-1]
            if basename in files:
                logger.warning("zip 内に重複ファイル名: %s (先勝ち)", name)
                continue
            files[basename] = zf.read(name)
        return files


def _collect_txt_from_dir(path: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.glob("*.txt"))}


def _feed_window(feed_info: pd.DataFrame | None, meta: SnapshotMeta) -> tuple[str, str] | None:
    """フィード有効期間 (YYYYMMDD, YYYYMMDD)。day_type の実効日クリップに使う (SD1)。

    feed_info.txt の feed_start_date/feed_end_date を第1候補、リポジトリ世代
    メタ (from_date/to_date) を第2候補とする。どちらも無ければ None (クリップなし)。
    """
    if feed_info is not None and not feed_info.empty and (
        {"feed_start_date", "feed_end_date"} <= set(feed_info.columns)
    ):
        start = str(feed_info.iloc[0]["feed_start_date"]).strip()
        end = str(feed_info.iloc[0]["feed_end_date"]).strip()
        if len(start) == 8 and len(end) == 8 and start.isdigit() and end.isdigit():
            return start, end
    start = (meta.from_date or "").replace("-", "")
    end = (meta.to_date or "").replace("-", "")
    if len(start) == 8 and len(end) == 8 and start.isdigit() and end.isdigit():
        return start, end
    return None


def load_snapshot(
    path: str | Path,
    config: Config | None = None,
    meta: SnapshotMeta | None = None,
) -> GtfsSnapshot:
    """GTFS zip またはディレクトリを GtfsSnapshot として読み込む。"""
    path = Path(path)
    if config is None:
        config = Config.load()
    if meta is None:
        meta = SnapshotMeta(source=str(path))

    if path.is_file():
        if not zipfile.is_zipfile(path):
            raise GtfsLoadError(f"zip ファイルではありません: {path}")
        raw_files = _collect_txt_from_zip(path)
    elif path.is_dir():
        raw_files = _collect_txt_from_dir(path)
    else:
        raise GtfsLoadError(f"入力が見つかりません: {path}")

    missing = REQUIRED_FILES - set(raw_files)
    if missing:
        raise GtfsLoadError(f"必須 GTFS ファイルがありません: {sorted(missing)} ({path})")

    tables: dict[str, pd.DataFrame] = {}
    for filename, data in raw_files.items():
        tables[filename.removesuffix(".txt")] = _read_csv_bytes(data, filename)

    if "calendar" not in tables and "calendar_dates" not in tables:
        logger.warning("%s: calendar.txt / calendar_dates.txt がどちらもありません", path)

    day_types = normalize_day_types(
        tables.get("calendar"),
        tables.get("calendar_dates"),
        calendar_dates_majority=config.get(
            "load", "day_types", "calendar_dates_majority", default=0.8
        ),
        short_service_max_days=config.get(
            "load", "day_types", "short_service_max_days", default=10
        ),
        feed_window=_feed_window(tables.get("feed_info"), meta),
        min_flag_day_ratio=config.get(
            "load", "day_types", "min_flag_day_ratio", default=0.5
        ),
    )

    snapshot = GtfsSnapshot(meta=meta, tables=tables, day_types=day_types)
    logger.info("読み込み完了: %s", snapshot.summary())
    return snapshot
