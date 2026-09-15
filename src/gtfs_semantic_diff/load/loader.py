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
import re
import zipfile
from pathlib import Path

import pandas as pd

from ..config import Config
from ..model import GtfsSnapshot, SnapshotMeta
from .day_types import normalize_day_types

logger = logging.getLogger(__name__)

REQUIRED_FILES = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}


class GtfsLoadError(ValueError):
    """GTFS として読めない入力 (必須ファイル欠落など)。

    メッセージはそのままエンドユーザーに表示される前提で、原因のファイル・行と
    「入力データ側の不備である」ことが分かる日本語で書く。`en` に英語版を持ち、
    Web の error_en に載る (i18n.md I2。省略時は日本語文で代用)。"""

    def __init__(self, message: str, en: str | None = None):
        super().__init__(message)
        self.en = en or message


def _parser_error_message(name: str, e: Exception) -> tuple[str, str]:
    """(日本語文, 英語文)。"""
    m = re.search(r"Expected (\d+) fields in line (\d+), saw (\d+)", str(e))
    if m:
        expected, line, saw = m.groups()
        return (
            f"{name} の {line}行目: 列数がヘッダ ({expected}列) と一致しません "
            f"(この行は {saw}列)。カンマを含む値が引用符 \" で囲まれていない等、"
            "フィード側データの CSV 形式の不備が原因です",
            f"{name} line {line}: the number of columns ({saw}) does not match "
            f"the header ({expected}). Likely an unquoted comma inside a value "
            "— a CSV formatting defect in the feed data",
        )
    return (
        f"{name}: CSV として解析できません (フィード側データの形式不備): {e}",
        f"{name}: cannot be parsed as CSV (a formatting defect in the feed "
        f"data): {e}",
    )


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
        except pd.errors.EmptyDataError:
            # 0バイト等の空ファイル (実例: 米沢市営バス旧世代の result.txt —
            # 検証ツール出力の混入)。ファイルの存在自体は L0 の記帳対象なので
            # 空テーブルとして受け入れ、比較は続行する
            logger.info("%s: 空ファイルのため 0 行テーブルとして読み込みます", name)
            return pd.DataFrame()
        except pd.errors.ParserError as e:
            # CSV 形式の不備 (実例: 立山町旧世代の translations.txt —
            # 引用符なしカンマで列数超過)。壊れた行を黙って読み飛ばすと
            # L0 網羅性が崩れるため、原因を明示して失敗させる
            ja, en = _parser_error_message(name, e)
            raise GtfsLoadError(ja, en=en) from e
    raise GtfsLoadError(
        f"{name}: 文字コードが UTF-8 / cp932 (Shift_JIS) のいずれでもなく"
        "読み込めません (フィード側データの形式不備)",
        en=f"{name}: the file is neither UTF-8 nor cp932 (Shift_JIS) encoded "
           "(a defect in the feed data)",
    )


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
            raise GtfsLoadError(f"zip ファイルではありません: {path}",
                                en=f"Not a zip file: {path}")
        raw_files = _collect_txt_from_zip(path)
    elif path.is_dir():
        raw_files = _collect_txt_from_dir(path)
    else:
        raise GtfsLoadError(f"入力が見つかりません: {path}",
                            en=f"Input not found: {path}")

    missing = REQUIRED_FILES - set(raw_files)
    if missing:
        raise GtfsLoadError(
            f"必須 GTFS ファイルがありません: {sorted(missing)} ({path})",
            en=f"Required GTFS files are missing: {sorted(missing)} ({path})")

    tables: dict[str, pd.DataFrame] = {}
    for filename, data in raw_files.items():
        df = _read_csv_bytes(data, filename)
        # 空ファイルの許容は必須外ファイルに限る。必須ファイルが空の GTFS は
        # 成立しないので、原因を明示して失敗させる
        if len(df.columns) == 0 and filename in REQUIRED_FILES:
            raise GtfsLoadError(
                f"{filename} が空です (フィード側データの不備)",
                en=f"{filename} is empty (a defect in the feed data)",
            )
        tables[filename.removesuffix(".txt")] = df

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
        dow_on=config.get("load", "day_types", "dow_on", default=0.6),
        dow_stray_max=config.get(
            "load", "day_types", "dow_stray_max", default=0.1
        ),
        dow_daily_min_cov=config.get(
            "load", "day_types", "dow_daily_min_cov", default=0.9
        ),
    )

    snapshot = GtfsSnapshot(meta=meta, tables=tables, day_types=day_types)
    logger.info("読み込み完了: %s", snapshot.summary())
    return snapshot
