"""L0: 2つの GtfsSnapshot 間の網羅的機械 diff (RawDiff 全列挙)。

方針 (docs/design/architecture.md):
- ファイル単位 → カラム単位 → 行単位 → フィールド単位の順に列挙する。
- この層では ID をキーにした素朴な突合で良い (意味的同定は L1 identity/ の仕事)。
- 列挙順序は決定的で、同じ入力ペアに対して常に同じ rawdiff ID が付く。

粒度の規約 (説明台帳の分母の定義):
- 片側にしかないファイル → file_added / file_removed 各1件 (行は列挙しない)
- 両側にあるファイルの片側にしかないカラム → column_added / column_removed 各1件
- 行の比較は両側共通カラムのみで行う
- 主キーで突合できたファイル → row_added / row_removed / field_changed (セル単位)
- 主キーが定義できない・重複するファイル → 行全体の多重集合比較にフォールバックし
  row_added / row_removed のみ (変更は削除+追加として現れる)
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter

import pandas as pd

from ..model import GtfsSnapshot, RawDiff, RawDiffSet
from ..model.rawdiff import (
    KIND_COLUMN_ADDED,
    KIND_COLUMN_REMOVED,
    KIND_FIELD_CHANGED,
    KIND_FILE_ADDED,
    KIND_FILE_REMOVED,
    KIND_ROW_ADDED,
    KIND_ROW_REMOVED,
)

logger = logging.getLogger(__name__)

# GTFS 各ファイルの行主キー (テーブル名は拡張子なし)。
# () は「単一行ファイル」を意味する。ここにないファイルはハッシュ突合。
KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "agency": ("agency_id",),
    "agency_jp": ("agency_id",),
    "stops": ("stop_id",),
    "routes": ("route_id",),
    "routes_jp": ("route_id",),
    "trips": ("trip_id",),
    "stop_times": ("trip_id", "stop_sequence"),
    "calendar": ("service_id",),
    "calendar_dates": ("service_id", "date"),
    "fare_attributes": ("fare_id",),
    "fare_rules": ("fare_id", "route_id", "origin_id", "destination_id", "contains_id"),
    "shapes": ("shape_id", "shape_pt_sequence"),
    "frequencies": ("trip_id", "start_time"),
    "transfers": ("from_stop_id", "to_stop_id"),
    "feed_info": (),
    "translations": (
        "table_name",
        "field_name",
        "language",
        "record_id",
        "record_sub_id",
        "field_value",
    ),
    "office_jp": ("office_id",),
    "levels": ("level_id",),
    "pathways": ("pathway_id",),
    "attributions": ("attribution_id",),
    "booking_rules": ("booking_rule_id",),
    "location_groups": ("location_group_id",),
}


def enumerate_rawdiffs(old: GtfsSnapshot, new: GtfsSnapshot) -> RawDiffSet:
    """2スナップショット間の RawDiff を決定的順序で全列挙し、連番 ID を付与する。"""
    pending: list[tuple] = []  # (file, kind, key, column, old_value, new_value)

    for table in sorted(old.table_names() | new.table_names()):
        filename = f"{table}.txt"
        old_df = old.table(table)
        new_df = new.table(table)
        if old_df is None:
            pending.append((filename, KIND_FILE_ADDED, (), "", None, None))
            continue
        if new_df is None:
            pending.append((filename, KIND_FILE_REMOVED, (), "", None, None))
            continue
        pending.extend(_diff_table(filename, table, old_df, new_df))

    diffs = [
        RawDiff(
            rawdiff_id=f"rawdiff_{i:06d}",
            file=file,
            kind=kind,
            key=key,
            column=column,
            old_value=old_value,
            new_value=new_value,
        )
        for i, (file, kind, key, column, old_value, new_value) in enumerate(pending, start=1)
    ]
    result = RawDiffSet(diffs)
    logger.info("L0 diff: %d 件 (%d ファイル)", len(result), len(result.count_by_file()))
    return result


def _diff_table(filename: str, table: str, old_df: pd.DataFrame, new_df: pd.DataFrame) -> list:
    out: list[tuple] = []
    old_cols = set(old_df.columns)
    new_cols = set(new_df.columns)

    for col in sorted(old_cols - new_cols):
        out.append((filename, KIND_COLUMN_REMOVED, (), col, None, None))
    for col in sorted(new_cols - old_cols):
        out.append((filename, KIND_COLUMN_ADDED, (), col, None, None))

    shared_cols = sorted(old_cols & new_cols)
    if not shared_cols:
        return out

    key_spec = KEY_COLUMNS.get(table)
    if key_spec == ():  # 単一行ファイル (feed_info)
        if len(old_df) == 1 and len(new_df) == 1:
            out.extend(_diff_single_row(filename, old_df, new_df, shared_cols))
            return out
        logger.warning("%s: 単一行ファイルが複数行のためハッシュ突合します", filename)
        out.extend(_diff_rows_hashed(filename, old_df, new_df, shared_cols))
        return out

    key_cols = [c for c in (key_spec or ()) if c in shared_cols]
    if key_spec is not None and len(key_cols) < len(key_spec):
        dropped = [c for c in key_spec if c not in shared_cols]
        logger.warning("%s: 主キーカラム %s が欠けているため残りで突合します", filename, dropped)
    if not key_cols:
        if key_spec is None:
            logger.info("%s: 主キー未定義のためハッシュ突合します", filename)
        out.extend(_diff_rows_hashed(filename, old_df, new_df, shared_cols))
        return out

    old_rows = _rows_by_key(old_df, key_cols, shared_cols)
    new_rows = _rows_by_key(new_df, key_cols, shared_cols)
    if old_rows is None or new_rows is None:
        logger.warning("%s: 主キー %s に重複があるためハッシュ突合します", filename, key_cols)
        out.extend(_diff_rows_hashed(filename, old_df, new_df, shared_cols))
        return out

    old_keys = set(old_rows)
    new_keys = set(new_rows)
    for key in sorted(old_keys - new_keys):
        out.append((filename, KIND_ROW_REMOVED, key, "", None, None))
    for key in sorted(new_keys - old_keys):
        out.append((filename, KIND_ROW_ADDED, key, "", None, None))
    for key in sorted(old_keys & new_keys):
        old_values = old_rows[key]
        new_values = new_rows[key]
        if old_values == new_values:
            continue
        for col, ov, nv in zip(shared_cols, old_values, new_values):
            if ov != nv:
                out.append((filename, KIND_FIELD_CHANGED, key, col, ov, nv))
    return out


def _rows_by_key(
    df: pd.DataFrame, key_cols: list[str], shared_cols: list[str]
) -> dict[tuple[str, ...], tuple[str, ...]] | None:
    """key タプル → 共通カラム値タプル。キー重複があれば None。"""
    keys = list(df[key_cols].itertuples(index=False, name=None))
    if len(set(keys)) != len(keys):
        return None
    values = df[shared_cols].itertuples(index=False, name=None)
    return dict(zip(keys, values))


def _diff_single_row(
    filename: str, old_df: pd.DataFrame, new_df: pd.DataFrame, shared_cols: list[str]
) -> list:
    out = []
    old_row = old_df.iloc[0]
    new_row = new_df.iloc[0]
    for col in shared_cols:
        if old_row[col] != new_row[col]:
            out.append((filename, KIND_FIELD_CHANGED, (), col, old_row[col], new_row[col]))
    return out


def _row_digest(values: tuple[str, ...]) -> str:
    joined = "\x1f".join(values)  # 区切りに現れない unit separator
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def _diff_rows_hashed(
    filename: str, old_df: pd.DataFrame, new_df: pd.DataFrame, shared_cols: list[str]
) -> list:
    """行全体の多重集合比較。key はダイジェスト+出現番号、行内容は値に残す。"""
    old_counter = Counter(old_df[shared_cols].itertuples(index=False, name=None))
    new_counter = Counter(new_df[shared_cols].itertuples(index=False, name=None))
    out = []
    # Counter の差はループの外で1回だけ計算する (差分計算は全行走査 O(N)。
    # ループ内で再計算すると O(差分行数×N) の二次爆発 — 山交バスの
    # stop_times 3万行で実質ハングした実例。docs/perf/diff0_hashed.md)
    removed = old_counter - new_counter
    for row in sorted(removed):
        content = ",".join(row)
        for i in range(removed[row]):
            out.append(
                (filename, KIND_ROW_REMOVED, (_row_digest(row), str(i)), "", content, None)
            )
    added = new_counter - old_counter
    for row in sorted(added):
        content = ",".join(row)
        for i in range(added[row]):
            out.append((filename, KIND_ROW_ADDED, (_row_digest(row), str(i)), "", None, content))
    return out
