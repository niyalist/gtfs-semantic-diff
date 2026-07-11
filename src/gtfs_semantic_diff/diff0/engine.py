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
- 行差分が閾値 (config [diff0].bulk_row_threshold) を超えたファイル →
  行単位の列挙をやめ、件数を保持した集約 RawDiff (rows_*_bulk) 各1件にする。
  検出ルールが行粒度の evidence を使うコアファイル (ROW_EVIDENCE_TABLES) は
  対象外。file_added/removed を1件とするのと同じ「粒度の規約」の一部であり、
  台帳の網羅性 (全差分がいずれかのイベントに説明される) は保たれる
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter

import pandas as pd

from ..model import GtfsSnapshot, RawDiff, RawDiffSet
from ..config import Config
from ..model.rawdiff import (
    KIND_COLUMN_ADDED,
    KIND_COLUMN_REMOVED,
    KIND_FIELD_CHANGED,
    KIND_FILE_ADDED,
    KIND_FILE_REMOVED,
    KIND_ROW_ADDED,
    KIND_ROW_REMOVED,
    KIND_ROWS_ADDED_BULK,
    KIND_ROWS_CHANGED_BULK,
    KIND_ROWS_REMOVED_BULK,
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

# 検出ルールが行粒度の evidence を要求するテーブル (集約 bulk の対象外)。
# ここを集約すると trip / 停留所 / カレンダー系ルールの evidence が消えて
# 台帳が壊れるため、規模によらず必ず行単位で列挙する。
# fare_* / translations / pass_* / 未知ファイルはファイル単位で消費される
# (rules/metadata.py ほか) ため集約してよい
ROW_EVIDENCE_TABLES = frozenset({
    "agency", "agency_jp", "stops", "routes", "routes_jp", "trips",
    "stop_times", "calendar", "calendar_dates", "shapes", "frequencies",
    "transfers", "feed_info", "office_jp",
})


def enumerate_rawdiffs(
    old: GtfsSnapshot, new: GtfsSnapshot, config: Config | None = None
) -> RawDiffSet:
    """2スナップショット間の RawDiff を決定的順序で全列挙し、連番 ID を付与する。

    config を渡すと [diff0].bulk_row_threshold による行差分の集約が有効になる
    (渡さなければ従来どおり全列挙 — 単体テスト・小規模用)。"""
    bulk_threshold = int(config.get("diff0", "bulk_row_threshold", default=0)) if config else 0
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
        threshold = 0 if table in ROW_EVIDENCE_TABLES else bulk_threshold
        pending.extend(_diff_table(filename, table, old_df, new_df, threshold))

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


def _diff_table(filename: str, table: str, old_df: pd.DataFrame,
                new_df: pd.DataFrame, bulk_threshold: int = 0) -> list:
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
        out.extend(_diff_rows_hashed(filename, old_df, new_df, shared_cols,
                                     bulk_threshold))
        return out

    key_cols = [c for c in (key_spec or ()) if c in shared_cols]
    if key_spec is not None and len(key_cols) < len(key_spec):
        dropped = [c for c in key_spec if c not in shared_cols]
        logger.warning("%s: 主キーカラム %s が欠けているため残りで突合します", filename, dropped)
    if not key_cols:
        if key_spec is None:
            logger.info("%s: 主キー未定義のためハッシュ突合します", filename)
        out.extend(_diff_rows_hashed(filename, old_df, new_df, shared_cols,
                                     bulk_threshold))
        return out

    # キー → 行ダイジェストの2パス方式: まず差分の所在だけを求め、値は差分行の
    # 分しか取り出さない (メモリはファイル規模でなく差分規模に比例する)
    old_digests = _digests_by_key(old_df, key_cols, shared_cols)
    new_digests = _digests_by_key(new_df, key_cols, shared_cols)
    if old_digests is None or new_digests is None:
        logger.warning("%s: 主キー %s に重複があるためハッシュ突合します", filename, key_cols)
        out.extend(_diff_rows_hashed(filename, old_df, new_df, shared_cols,
                                     bulk_threshold))
        return out

    removed = old_digests.keys() - new_digests.keys()
    added = new_digests.keys() - old_digests.keys()
    changed = {k for k in old_digests.keys() & new_digests.keys()
               if old_digests[k] != new_digests[k]}

    if bulk_threshold and len(removed) + len(added) + len(changed) > bulk_threshold:
        logger.warning(
            "%s: 行差分 %d 件 (>%d) のため集約 RawDiff にします (削除 %d / 追加 %d / 変更 %d)",
            filename, len(removed) + len(added) + len(changed), bulk_threshold,
            len(removed), len(added), len(changed))
        if removed:
            out.append((filename, KIND_ROWS_REMOVED_BULK, (), "",
                        str(len(removed)), None))
        if added:
            out.append((filename, KIND_ROWS_ADDED_BULK, (), "",
                        None, str(len(added))))
        if changed:
            out.append((filename, KIND_ROWS_CHANGED_BULK, (), "",
                        str(len(changed)), str(len(changed))))
        return out

    old_values = _values_for_keys(old_df, key_cols, shared_cols, changed)
    new_values = _values_for_keys(new_df, key_cols, shared_cols, changed)
    for key in sorted(removed):
        out.append((filename, KIND_ROW_REMOVED, key, "", None, None))
    for key in sorted(added):
        out.append((filename, KIND_ROW_ADDED, key, "", None, None))
    for key in sorted(changed):
        for col, ov, nv in zip(shared_cols, old_values[key], new_values[key]):
            if ov != nv:
                out.append((filename, KIND_FIELD_CHANGED, key, col, ov, nv))
    return out


def _digests_by_key(
    df: pd.DataFrame, key_cols: list[str], shared_cols: list[str]
) -> dict[tuple[str, ...], str] | None:
    """key タプル → 行内容ダイジェスト。キー重複があれば None。

    値タプルを保持せずダイジェスト (sha1 全40桁 = 160bit、衝突は実質ゼロ) だけを
    持つことで、200万行級ファイルでもメモリを抑える。"""
    keys = list(df[key_cols].itertuples(index=False, name=None))
    if len(set(keys)) != len(keys):
        return None
    digests = (
        hashlib.sha1("\x1f".join(v).encode("utf-8")).hexdigest()
        for v in df[shared_cols].itertuples(index=False, name=None)
    )
    return dict(zip(keys, digests))


def _values_for_keys(
    df: pd.DataFrame, key_cols: list[str], shared_cols: list[str], wanted: set
) -> dict[tuple[str, ...], tuple[str, ...]]:
    """wanted のキーに該当する行の共通カラム値タプルだけを取り出す。"""
    if not wanted:
        return {}
    out = {}
    keys = df[key_cols].itertuples(index=False, name=None)
    values = df[shared_cols].itertuples(index=False, name=None)
    for k, v in zip(keys, values):
        if k in wanted:
            out[k] = v
    return out


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
    filename: str, old_df: pd.DataFrame, new_df: pd.DataFrame,
    shared_cols: list[str], bulk_threshold: int = 0
) -> list:
    """行全体の多重集合比較。key はダイジェスト+出現番号、行内容は値に残す。"""
    old_counter = Counter(old_df[shared_cols].itertuples(index=False, name=None))
    new_counter = Counter(new_df[shared_cols].itertuples(index=False, name=None))
    out = []
    # Counter の差はループの外で1回だけ計算する (差分計算は全行走査 O(N)。
    # ループ内で再計算すると O(差分行数×N) の二次爆発 — 山交バスの
    # stop_times 3万行で実質ハングした実例。docs/perf/diff0_hashed.md)
    removed = old_counter - new_counter
    added_counter = new_counter - old_counter
    n_removed = sum(removed.values())
    n_added = sum(added_counter.values())
    if bulk_threshold and n_removed + n_added > bulk_threshold:
        logger.warning(
            "%s: 行差分 %d 件 (>%d) のため集約 RawDiff にします (削除 %d / 追加 %d)",
            filename, n_removed + n_added, bulk_threshold, n_removed, n_added)
        if n_removed:
            out.append((filename, KIND_ROWS_REMOVED_BULK, (), "",
                        str(n_removed), None))
        if n_added:
            out.append((filename, KIND_ROWS_ADDED_BULK, (), "",
                        None, str(n_added)))
        return out
    for row in sorted(removed):
        content = ",".join(row)
        for i in range(removed[row]):
            out.append(
                (filename, KIND_ROW_REMOVED, (_row_digest(row), str(i)), "", content, None)
            )
    for row in sorted(added_counter):
        content = ",".join(row)
        for i in range(added_counter[row]):
            out.append((filename, KIND_ROW_ADDED, (_row_digest(row), str(i)), "", None, content))
    return out
