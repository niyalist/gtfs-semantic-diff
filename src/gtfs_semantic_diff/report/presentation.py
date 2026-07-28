"""プレゼンテーションモデル生成 (docs/design/presentation.md、凍結要件 R1〜R17)。

events + identity + trip_delta から、路線 (route_group) ページのビューモデルを
決定的ルールで合成する。コア (イベント・説明台帳) は読み取りのみ (設計原則1)。
スコープは「路線に紐付く変更」— 運賃・メタデータ等は対象外 (検証モード側)。

構成 (1 route_group = 1 ページ):
  overview   ① 路線概要 (方向グループ・運行系統・代表停車列・地図用ポリライン)
  summary    ② 変化サマリー (Lev.1〜5 のカスケード、上位が下位を吸収)
  band_matrix ③ 時間帯別本数 (方向グループ→曜日固定順→系統、集計→内訳)
  timetables  ④ 新旧時刻表 (LCS 併合の停留所軸、trip 対応付き = 差分表示の素材)
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from itertools import combinations

from ..config import Config
from ..events.rules.patterns import classify_sequence_changes
from ..events.timebands import TimeBands
from ..events.tripdelta import TripDelta, TripInfo
from ..identity import IdentityResult
from ..identity.route_group import stop_jaccard
from ..model import ChangeEventSet
from ..model.matchgraph import ENTITY_PATTERN_CLUSTER

logger = logging.getLogger(__name__)

# R16 (M10 改): 曜日の固定順。dow_* (曜日指定) は 毎日 と 特定日 の間に
# ビット列 (早い曜日優先) で決定的に整列、運行日なし (inactive) は最後
DAY_ORDER = ["weekday", "saturday", "sunday_holiday", "weekend", "daily",
             "irregular", "inactive"]

_PATTERN_EVENT_TYPES = {
    "PATTERN_EXTENDED", "PATTERN_TRUNCATED", "STOP_INSERTED_IN_PATTERN",
    "STOP_REMOVED_FROM_PATTERN", "DETOUR_ADDED", "DETOUR_REMOVED",
}

_DAILY_INDEX = DAY_ORDER.index("daily")


# SD5b: 表示から畳む重複世界の便 (代表世界以外) の番兵ラベル
_DUP = "__dup_world__"


def date_runs_year_split(dates, max_runs: int):
    """YYYYMMDD 昇順リスト → 連続日ラン [[a,b],…]。

    連続していれば月を跨いでも繋げるが、**年境 (12/31|1/1) では必ず分割**する
    (2026-07-25 ユーザー指定 — 「3/1〜10/31」は1本、「12/30〜1/3」は
    「12/30〜12/31」「1/1〜1/3」)。戻り値: (runs[:max_runs], あふれたラン数)。"""
    import datetime as _dt

    def d(t):
        return _dt.date(int(t[:4]), int(t[4:6]), int(t[6:8]))

    runs: list[list[str]] = []
    start = prev = None
    for t in dates:
        if (prev is not None and (d(t) - d(prev)).days == 1
                and t[:4] == prev[:4]):
            prev = t
            continue
        if start is not None:
            runs.append([start, prev])
        start = prev = t
    if start is not None:
        runs.append([start, prev])
    return runs[:max_runs], max(0, len(runs) - max_runs)


_NAT_TOKEN = None  # 遅延コンパイル (import 時コストの回避)


def natural_sort_key(name: str) -> tuple:
    """G4 (kyoto_review.md §4): 路線名の自然順ソートキー。

    NFKC 正規化 (全角数字→半角。Unicode 標準変換で言語特化ではない) の上で
    「文字列部分と数字部分の交互トークン」に分解し、数字は数値として比較する。
    - 桁数混在: 1 < 2 < 10 < 105 (文字列比較の 1,10,105,2 を解消)
    - 漢字接頭辞+数字 (上31 型): 接頭辞が第1トークンなので系統はまとまり、
      その中で番号が数値順。数字だけの抽出はしない
    - 意味の解釈 (特/快速等の語彙表・読み仮名) はしない — 接頭辞同士の順は
      文字コード順 (決定的であることを優先)
    数値同点 (001 vs 1) は元文字列でタイブレーク (決定性)。"""
    import re
    import unicodedata

    global _NAT_TOKEN
    if _NAT_TOKEN is None:
        _NAT_TOKEN = re.compile(r"\d+|\D+")
    key = []
    for tok in _NAT_TOKEN.findall(unicodedata.normalize("NFKC", name)):
        if tok.isdigit():
            key.append((0, int(tok), ""))
        else:
            key.append((1, 0, tok))
    return (tuple(key), name)


def base_day(day_type: str) -> str:
    """SD5b: 表示セルラベル "saturday@2" の基底 day_type。"""
    return day_type.partition("@")[0]


def day_sort_key(day_type: str) -> tuple:
    day_type, _, _suffix = day_type.partition("@")
    suffix = int(_suffix) if _suffix.isdigit() else 0
    if day_type.startswith("dow_"):
        # '1' < '0' になるよう反転: 月曜を含むパターンが先に来る
        bits = day_type[4:]
        inverted = "".join("0" if b == "1" else "1" for b in bits)
        return (_DAILY_INDEX, 1, inverted, suffix)
    if day_type in DAY_ORDER:
        return (DAY_ORDER.index(day_type), 0, "", suffix)
    return (len(DAY_ORDER), 0, day_type, suffix)


# --- 便ラベル (R19): 便ごとの変化を代表1ラベルに分類 ---

# 集約 (折りたたみチップ・ダイジェスト) の表示順もこの順
TRIP_LABEL_ORDER = [
    "added", "removed", "rerouted", "shortened", "extended",
    "retimed", "retimed_minor", "unchanged",
]


def trip_pair_label(old: TripInfo, new: TripInfo, minor_max_min: float) -> str:
    """対応付いた便対の代表1ラベル。

    複数の変化が重なる便も代表1つに畳む (R19): 経路の変化はほぼ必ず時刻の
    変化を伴うため、優先順位は「経路系 > 時刻系」。停車列の変化の分類は
    B群イベントと同じ classify_sequence_changes を使い、検出と表示を揃える。
    時刻は表示粒度 (分) で比較する (④時刻表の変更表示と同じ基準)。
    """
    if old.base_seq != new.base_seq:
        kinds = {k for k, _ in classify_sequence_changes(old.base_seq, new.base_seq)}
        if kinds == {"PATTERN_TRUNCATED"}:
            return "shortened"
        if kinds == {"PATTERN_EXTENDED"}:
            return "extended"
        return "rerouted"
    max_shift = 0
    for (oa, od), (na, nd) in zip(old.times, new.times):
        a = _cell_minute(od or oa)
        b = _cell_minute(nd or na)
        if a is None and b is None:
            continue
        if a is None or b is None:
            return "retimed"  # 時刻の出現/消滅は微調整とみなさない
        max_shift = max(max_shift, abs(a - b))
    if max_shift == 0:
        return "unchanged"
    return "retimed_minor" if max_shift <= minor_max_min else "retimed"


# --- 方向グループの順序整合度 (R15 改訂 2026-07-07) ---


def order_agreement(stops_a: list[str], stops_b: list[str]) -> tuple[float | None, int]:
    """共有停留所ペアのうち相対順序が一致する割合と共有停留所数を返す。

    位置は初出で判定 (循環線の重複停留所対策)。共有ペアが無ければ (None, 数)。
    1.0 = 完全に同方向、0.0 = 完全に逆方向。
    """
    pos_a: dict[str, int] = {}
    for i, s in enumerate(stops_a):
        pos_a.setdefault(s, i)
    pos_b: dict[str, int] = {}
    for i, s in enumerate(stops_b):
        pos_b.setdefault(s, i)
    shared = [s for s in pos_a if s in pos_b]
    same = 0
    total = 0
    for x, y in combinations(shared, 2):
        d = (pos_a[x] - pos_a[y]) * (pos_b[x] - pos_b[y])
        if d == 0:
            continue
        total += 1
        if d > 0:
            same += 1
    if total == 0:
        return None, len(shared)
    return same / total, len(shared)


# --- 時刻表の列ソート (参考: LibreDiaNet timetable-column-sort) ---


def _cell_minute(value: str | None) -> int | None:
    from ..events.timebands import parse_gtfs_time

    if not value:
        return None
    sec = parse_gtfs_time(value)
    return sec // 60 if sec is not None else None


def _compare_columns(ta: list[int | None], tb: list[int | None]) -> int:
    """時刻表2列の前後関係。-1: a が左 / 1: a が右 / 0: 同値・判断不能。

    - 共有停留所 (両列に時刻がある軸行) があれば、最初の共有行の時刻で比較。
      同時刻なら次の共有行へ (全行同時刻なら 0 = 元の順序を保つ)
    - 共有が無く、停車区間が軸上で離れている場合は境界時刻で比較する:
      a の区間が上流側で終わるなら「a の最終時刻 ≤ b の最初の時刻」のとき a が左
      (LibreDiaNet の colSpan>1 分岐に相当)
    """
    shared = [
        i for i in range(min(len(ta), len(tb)))
        if ta[i] is not None and tb[i] is not None
    ]
    if shared:
        # 最初の共有行 = 出発順。同時刻発なら最後の共有行 = 先着順で決める
        # (経路・所要の違う同時発便の交差で、逆転して見える行を最小化する)
        if ta[shared[0]] != tb[shared[0]]:
            return -1 if ta[shared[0]] < tb[shared[0]] else 1
        if ta[shared[-1]] != tb[shared[-1]]:
            return -1 if ta[shared[-1]] < tb[shared[-1]] else 1
        for i in shared:
            if ta[i] != tb[i]:
                return -1 if ta[i] < tb[i] else 1
        return 0
    a_idx = [i for i, v in enumerate(ta) if v is not None]
    b_idx = [i for i, v in enumerate(tb) if v is not None]
    if not a_idx or not b_idx:
        return 0
    if a_idx[-1] < b_idx[0]:
        return -1 if ta[a_idx[-1]] <= tb[b_idx[0]] else 1
    if b_idx[-1] < a_idx[0]:
        return 1 if tb[b_idx[-1]] <= ta[a_idx[0]] else -1
    return 0  # 互い違いの欠け (通過等) — 判断不能


def sort_timetable_columns(columns: list[dict]) -> list[dict]:
    """列 (1列=1便) を「どの停留所でも時刻が左→右で単調」になるよう並べる。

    途中始発・途中止まりの便は始発時刻 (自分の最初の停留所の時刻) だけでは
    比較できない — 全便が1つの停留所を共有するとは限らないため、単一キーの
    ソートでは交差が生じる。軸上の時刻ベクトルの対比較 + 挿入ソートで解く。
    初期順序は始発時刻順 (決定的)、比較不能な対は初期順序を保つ。
    """

    def minutes(col: dict) -> list[int | None]:
        times = col["times_new"] if col["times_new"] is not None else col["times_old"]
        return [_cell_minute(v) if v else None for v in (times or [])]

    pre = sorted(columns, key=lambda c: (c["sort_key"], c["trip_id_new"] or
                                         c["trip_id_old"] or ""))
    vecs = [minutes(c) for c in pre]
    ordered: list[tuple[dict, list[int | None]]] = []
    for c, vec in zip(pre, vecs):
        pos = len(ordered)
        for j, (_, svec) in enumerate(ordered):
            if _compare_columns(vec, svec) < 0:
                pos = j
                break
        ordered.insert(pos, (c, vec))
    # 隣接バブル整定: 挿入だけでは解けない交差 (非推移な対や後から入った列) を
    # 比較関数が逆転を報告しなくなるまで解消する。パス数は列数で上限
    # (追い越し便など本質的に単調化できない対は 0 を返すため動かない)
    for _ in range(len(ordered)):
        swapped = False
        for i in range(len(ordered) - 1):
            if _compare_columns(ordered[i][1], ordered[i + 1][1]) > 0:
                ordered[i], ordered[i + 1] = ordered[i + 1], ordered[i]
                swapped = True
        if not swapped:
            break
    return [c for c, _ in ordered]


def _is_subsequence(a: tuple, b: tuple) -> bool:
    """a が b の (連続とは限らない) 部分列か。区間便・通過便の完全包含判定に使う。"""
    it = iter(b)
    return all(x in it for x in a)


# --- 時刻表の分冊 (R17 改 2026-07-08) ---


def _gap_runs(positions: list[int]) -> int:
    """便の運行範囲内で経由行が途切れる回数 (時刻表の読みにくさの目的量)。"""
    pos = [p for p in positions if p >= 0]
    if len(pos) < 2:
        return 0
    served = set(pos)
    runs, in_gap = 0, False
    for i in range(pos[0], pos[-1] + 1):
        if i not in served:
            if not in_gap:
                runs += 1
                in_gap = True
        else:
            in_gap = False
    return runs


def _specs_gap(specs: list[tuple]) -> int:
    """列候補 (status, old, new) 群を1枚に載せたときの飛び合計。"""
    seqs = set()
    for _, o, nw in specs:
        if o is not None:
            seqs.add(o.base_seq)
        if nw is not None:
            seqs.add(nw.base_seq)
    axis = build_stop_axis(sorted(seqs))
    total = 0
    for _, o, nw in specs:
        for t in (o, nw):
            if t is not None:
                total += _gap_runs(align_to_axis(t.base_seq, axis))
    return total


def _specs_alignments(specs: list[tuple]) -> int:
    """飛びの分母 (表に載る新旧の時刻列の本数)。"""
    return sum((s[1] is not None) + (s[2] is not None) for s in specs)


def group_sheets(spec_groups: list[list[tuple]], max_cost: float) -> list[list[tuple]]:
    """分冊 (sheet) の目的駆動グループ化。

    系統ごとの列候補グループを初期状態に、「併合したときの飛びの増加量 / 便数」
    が最小の対から、増加量が max_cost 以下の間だけ貪欲に併合する (決定的)。
    区間便 (包含) は増加量 0 で自然に併合され、経由違い・循環の逆回りは
    増加量が大きく分冊のまま残る。
    """
    groups = [list(g) for g in spec_groups if g]
    costs = [_specs_gap(g) for g in groups]
    while len(groups) > 1:
        best = None  # (cost, i, j, merged_gap)
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                merged_gap = _specs_gap(groups[i] + groups[j])
                cost = (merged_gap - costs[i] - costs[j]) / (
                    len(groups[i]) + len(groups[j])
                )
                if best is None or cost < best[0]:
                    best = (cost, i, j, merged_gap)
        if best is None or best[0] > max_cost:
            break
        _, i, j, merged_gap = best
        groups[i] = groups[i] + groups[j]
        costs[i] = merged_gap
        del groups[j]
        del costs[j]
    return groups


def _sheet_sort_key(specs: list[tuple]) -> str:
    """分冊の決定的な並び順キー (便数同数のとき): 最小の trip_id。"""
    return min((nw or o).trip_id for _, o, nw in specs)


def sheet_labels(sheets: list[list[tuple]]) -> list[str | None]:
    """各分冊のラベル。1枚なら None。

    - 識別停留所 (その分冊にだけある停留所) があれば頻度上位2つで「A・B経由」
    - 無い (同一停留所集合で順序違い = 循環の逆回り等) なら、代表停車列同士の
      最初の相違停留所で「◯◯先回り」
    """
    if len(sheets) <= 1:
        return [None] * len(sheets)

    def stop_freq(specs) -> dict[str, int]:
        freq: dict[str, int] = defaultdict(int)
        for _, o, nw in specs:
            t = nw or o
            for s in set(t.base_seq):
                freq[s] += 1
        return freq

    def rep_seq(specs) -> tuple:
        counts: dict[tuple, int] = defaultdict(int)
        for _, o, nw in specs:
            counts[(nw or o).base_seq] += 1
        return max(counts, key=lambda s: (counts[s], s))

    stop_sets = [set(stop_freq(sp)) for sp in sheets]
    labels: list[str | None] = []
    for i, specs in enumerate(sheets):
        others: set[str] = set()
        for j, ss in enumerate(stop_sets):
            if j != i:
                others |= ss
        dist = stop_sets[i] - others
        if dist:
            freq = stop_freq(specs)
            top = sorted(dist, key=lambda s: (-freq[s], s))[:2]
            labels.append("・".join(top) + "経由")
            continue
        mine = rep_seq(specs)
        other = rep_seq(sheets[0] if i else sheets[1])
        label = None
        for a, b in zip(mine, other):
            if a != b:
                label = f"{a}先回り"
                break
        labels.append(label or f"経路{i + 1}")
    # 同名ラベルの重複解消 (「六地蔵先回り」×2 等): 2つ目以降に連番
    seen: dict[str, int] = defaultdict(int)
    for i, lb in enumerate(labels):
        if lb is None:
            continue
        seen[lb] += 1
        if seen[lb] > 1:
            labels[i] = f"{lb}（{seen[lb]}）"
    return labels


def _loop_leg_label(group_label: str, terminal: str,
                    mine: list[str], other: list[str]) -> str:
    """循環の向き (leg) の表示名: 「◯◯ 循環（△△先回り）」。

    △△ = 自回りの代表停車列が相手回りと最初に食い違う停留所 —
    分冊ラベル (sheet_labels) と同じ規則で、B層 (向き) と D層 (分冊) が
    同じ語彙を共有する (G3、orientation.md §5)。起終点 (terminal) 自身は
    候補から除く — 逆回りの起点が別停留所の循環で「桑名駅西口 循環
    （桑名駅西口先回り）」のような冗長ラベルになるのを防ぐ。
    相違が見つからない縮退では群ラベルのみ返す (呼び出し側で連番)。"""
    for a, b in zip(mine, other):
        if a != b and a != terminal:
            return f"{group_label}（{a}先回り）"
    return group_label


# --- 停留所軸の併合 (R17) ---


def _lcs_table(a: tuple, b: tuple) -> list[list[int]]:
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp


def merge_axis(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    """2列の最短共通超列 (LCS ベース)。結果は a・b 双方を部分列として含む。"""
    dp = _lcs_table(a, b)
    out: list[str] = []
    i, j = len(a), len(b)
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            out.append(a[i - 1])
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            out.append(a[i - 1])
            i -= 1
        else:
            out.append(b[j - 1])
            j -= 1
    out.extend(reversed(a[:i]))
    out.extend(reversed(b[:j]))
    return tuple(reversed(out))


def build_stop_axis(sequences: list[tuple[str, ...]]) -> tuple[str, ...]:
    """全停車列を1本の停留所軸に併合する (全列の超列)。長い列から決定的順序で。"""
    if not sequences:
        return ()
    ordered = sorted(set(sequences), key=lambda s: (-len(s), s))
    axis = ordered[0]
    for seq in ordered[1:]:
        axis = merge_axis(axis, seq)
    return axis


def align_to_axis(seq: tuple[str, ...], axis: tuple[str, ...]) -> list[int]:
    """seq 各位置 → 軸位置 (貪欲 in-order)。軸に無い停留所は -1 (表示対象外)。

    軸は同一バケット内の全停車列 (経路変更 trip の旧列を含む) の超列として
    構築されるため、通常 -1 は出ないが、防御的に扱う。"""
    positions = []
    k = 0
    for stop in seq:
        j = k
        while j < len(axis) and axis[j] != stop:
            j += 1
        if j < len(axis):
            positions.append(j)
            k = j + 1
        else:
            positions.append(-1)
    return positions


# --- 本体 ---


def build_presentation(
    event_set: ChangeEventSet,
    identity: IdentityResult,
    trip_delta: TripDelta,
    config: Config,
    day_worlds=None,
) -> dict:
    """day_worlds (events.day_worlds.WorldContext | None): SD5b。
    与えると複数世界ラベルの曜日タブ・③④が対応セル単位になる
    (service_days.md §9.4 案C'。None なら従来表示)。"""
    builder = _Builder(event_set, identity, trip_delta, config,
                       day_worlds=day_worlds)
    return builder.build()


class _Builder:
    def __init__(self, event_set, identity, trip_delta, config, day_worlds=None):
        self.events = event_set.events
        self.identity = identity
        self.delta = trip_delta
        self.config = config
        self.bands = TimeBands(
            config.get("events", "frequency", "time_bands", default=[])
        )
        self.min_trips = config.get("presentation", "system_min_trips", default=2)
        self.full_coverage = config.get("presentation", "full_coverage", default=0.9)
        self.retime_minor = config.get(
            "presentation", "retime_minor_max_min", default=5
        )
        self.pair_jaccard = config.get(
            "presentation", "direction_pair_jaccard", default=0.6
        )
        self.reversed_max = config.get(
            "presentation", "direction_reversed_max_agreement", default=0.2
        )
        self.same_min = config.get(
            "presentation", "direction_same_min_agreement", default=0.8
        )
        self.min_shared = config.get(
            "presentation", "direction_min_shared_stops", default=3
        )
        self.accept = config.get("events", "accept_confidence", default=0.5)

        # M9: ページは新世代を背骨に。世代間で対応した旧 family は
        # 新側 group のページへ写す (route_identity_review.md §3.3.1)
        from ..identity.builder import page_family_maps

        old_page, new_page = page_family_maps(identity)
        self.f2g = {**old_page, **new_page}
        # 旧名称注記: 対応成分 (非降格) の旧 family 名を新側 group に紐づける
        self.former_by_group: dict[str, set[str]] = defaultdict(set)
        for comp in identity.family_components:
            if comp["demoted"]:
                continue
            renamed = set(comp["old"]) - set(comp["new"])
            for nf in comp["new"]:
                group = identity.new_family_to_group.get(nf, nf)
                self.former_by_group[group] |= renamed
        # 類似候補注記 (受理未満・降格): 廃止/新設ページの相互参照
        from ..identity.route_family import METHOD_CANDIDATE
        from ..model.matchgraph import ENTITY_ROUTE_FAMILY

        self.cand_old_group: dict[str, list] = defaultdict(list)
        self.cand_new_group: dict[str, list] = defaultdict(list)
        for e in identity.graph.for_type(ENTITY_ROUTE_FAMILY):
            if e.method != METHOD_CANDIDATE:
                continue
            og = identity.old_family_to_group.get(e.old_id, e.old_id)
            ng = identity.new_family_to_group.get(e.new_id, e.new_id)
            self.cand_old_group[og].append((e.confidence, e.new_id))
            self.cand_new_group[ng].append((e.confidence, e.old_id))
        # trip → cluster (base_seq 経由)
        self.old_seq2cluster = self._seq_to_cluster(identity.old_pattern_clusters)
        self.new_seq2cluster = self._seq_to_cluster(identity.new_pattern_clusters)
        # 停留所座標。「学校前」「教会前」のような一般名は同一フィード内の
        # 離れた場所に複数クラスタが立つ (茅ヶ崎えぼし号の実例: 教会前が
        # 東部循環と北部循環で約3km 離れて2箇所)。基底名1本の表だと先勝ちの
        # 座標が別路線の地図に混入するため、(family, base_name) を第1キーに
        # して路線側のクラスタを引き、基底名のみはフォールバック (新世代優先)
        self.coords: dict[str, tuple[float, float]] = {}
        self.coords_family: dict[tuple[str, str], tuple[float, float]] = {}
        for clusters in (identity.new_stop_clusters, identity.old_stop_clusters):
            for c in clusters.values():
                self.coords.setdefault(c.base_name, (c.lat, c.lon))
                for fam in c.route_families:
                    self.coords_family.setdefault((fam, c.base_name), (c.lat, c.lon))
        # 停留所の世代別存在 (時刻表の軸ステータス用)
        self.old_stop_names = {c.base_name for c in identity.old_stop_clusters.values()}
        self.new_stop_names = {c.base_name for c in identity.new_stop_clusters.values()}
        # 停留所 → 通る route_group 集合 (主要停留所=ハブ判定用)
        self.hub_min_groups = config.get("presentation", "hub_min_groups", default=3)
        self.stop_groups: dict[str, set[str]] = defaultdict(set)
        for clusters in (identity.old_pattern_clusters, identity.new_pattern_clusters):
            for c in clusters:
                g = self.f2g.get(c.family)
                if not g:
                    continue
                for pattern in c.patterns:
                    for stop in pattern.base_names:
                        self.stop_groups[stop].add(g)

        # SD5b (案C'): 複数世界ラベルの表示セル。世界パターンの世代間対応
        # (2信号) + 便対応 v1 の多数決 (厳密 1:1、フロー降順の貪欲) で
        # セルを整列し、trip の表示上の day_type を "label@N" に細分する。
        # コアの events は不変。1世界ラベル・day_worlds なしでは完全に従来どおり
        self.wc = day_worlds
        self._disp: dict = {}  # (side, family, direction, label, world_id) → 表示ラベル
        self.group_day_cells: dict[str, dict] = {}  # group → 表示ラベル → メタ
        # 表示整合セルフチェック (PI 違反の台帳)。warning ログに流すだけでなく
        # bundle に載せ、検証モードで可視化する (ui_quality.md S3)
        self.self_check: list[dict] = []
        # 双子写像 (SD5b 第2弾): パターン内の世界は内容同一なので、
        # 非代表世界の便 → 代表世界の同内容便 (署名順 zip)。表示側の対応・
        # チップ・③④はこの正規形から作る (content/flow の区別なく整合する)
        self._twin: dict = {}  # (side, trip_id) → 代表世界の TripInfo
        if self.wc is not None:
            self._build_day_cells()
            self._build_twins()

    def _build_day_cells(self) -> None:
        from collections import Counter as _Counter

        from ..events.day_worlds import match_patterns

        wc = self.wc
        dates_max = self.config.get("events", "service_days", "dates_list_max",
                                    default=30)
        # 表示セルの整列は (route_group, 方向, ラベル) 粒度で行う。
        # family 名が世代間で張り替わる路線 (M9 対応) では (family, …) キーの
        # ままだと旧/新のパターンが別キーに割れ、flow 整列が不発になって
        # 「48→0▼ / 0→47▲」の見かけ分裂を生む (桑名 名古屋桑名高速線の実例)
        def gkey(fam, direction, label):
            g = self.f2g.get(fam)
            return (g, direction, label) if g else None

        merged_old: dict = defaultdict(list)
        merged_new: dict = defaultdict(list)
        for (fam, direction, label), pats in wc.old_patterns.items():
            if (label in wc.old.multi_labels or label in wc.new.multi_labels):
                k = gkey(fam, direction, label)
                if k:
                    merged_old[k].extend((fam, p) for p in pats)
        for (fam, direction, label), pats in wc.new_patterns.items():
            if (label in wc.old.multi_labels or label in wc.new.multi_labels):
                k = gkey(fam, direction, label)
                if k:
                    merged_new[k].extend((fam, p) for p in pats)

        # 便対応 v1 の実対応 → 世界間フロー (group 粒度で架橋)。
        # exact_pairs も数える — 改正で時刻が変わらない路線は対応が全部 exact
        # になり、1便の増減だけで digest が割れて flow が組めなくなる
        # (桑名 栄桑名高速線: exact 207 / modified 0 の実例)
        from itertools import chain

        flows: dict = {}
        for o, n in chain(self.delta.modified, self.delta.exact_pairs):
            ko = gkey(o.family, o.direction, o.day_type)
            kn = gkey(n.family, n.direction, n.day_type)
            if ko is None or ko != kn:
                continue
            wo = wc.old.world_of(o.service_id)
            wn = wc.new.world_of(n.service_id)
            flows.setdefault(ko, _Counter())[(wo, wn)] += 1

        per_gl: dict = defaultdict(list)
        for k in sorted(set(merged_old) | set(merged_new), key=str):
            group, direction, label = k
            o_entries = sorted(merged_old.get(k, []),
                               key=lambda fp: (fp[1].dates[:1], fp[0]))
            n_entries = sorted(merged_new.get(k, []),
                               key=lambda fp: (fp[1].dates[:1], fp[0]))
            o_pats = [p for _, p in o_entries]
            n_pats = [p for _, p in n_entries]
            o_fams = [f for f, _ in o_entries]
            n_fams = [f for f, _ in n_entries]
            matches = match_patterns(o_pats, n_pats)
            cells = [(i, j, sg) for i, j, sg in matches if sg is not None]
            un_old = [i for i, j, sg in matches if sg is None and i is not None]
            un_new = [j for i, j, sg in matches if sg is None and j is not None]
            w2p_o = {w: idx for idx, p in enumerate(o_pats)
                     for w in p.world_ids}
            w2p_n = {w: idx for idx, p in enumerate(n_pats)
                     for w in p.world_ids}
            pf: _Counter = _Counter()
            for (wo, wn), cnt in flows.get(k, _Counter()).items():
                i, j = w2p_o.get(wo), w2p_n.get(wn)
                if i in un_old and j in un_new:
                    pf[(i, j)] += cnt
            used_o: set = set()
            used_n: set = set()
            for (i, j), _cnt in sorted(pf.items(), key=lambda kv: (-kv[1], kv[0])):
                if i in used_o or j in used_n:
                    continue
                used_o.add(i)
                used_n.add(j)
                cells.append((i, j, "flow"))
            cells.extend((i, None, None) for i in un_old if i not in used_o)
            cells.extend((None, j, None) for j in un_new if j not in used_n)
            per_gl[(group, label)].append(
                (direction, o_pats, n_pats, o_fams, n_fams, cells))

        for (group, label), entries in per_gl.items():
            cell_meta: dict = {}
            for direction, o_pats, n_pats, o_fams, n_fams, cells in entries:
                for i, j, sg in cells:
                    od = o_pats[i].dates if i is not None else ()
                    nd = n_pats[j].dates if j is not None else ()
                    ck = (od, nd)
                    rank = {"content": 3, "dates": 2, "flow": 1}.get(sg, 0)
                    if ck not in cell_meta or rank > cell_meta[ck]["_rank"]:
                        runs_max = self.config.get(
                            "report", "note_runs_max", default=8)
                        ro, ro_more = date_runs_year_split(od, runs_max)
                        rn, rn_more = date_runs_year_split(nd, runs_max)
                        by_id_o = self.wc.old.by_id()
                        by_id_n = self.wc.new.by_id()
                        mo = [by_id_o[w] for w in
                              (o_pats[i].world_ids if i is not None else ())
                              if w in by_id_o]
                        mn = [by_id_n[w] for w in
                              (n_pats[j].world_ids if j is not None else ())
                              if w in by_id_n]
                        cell_meta[ck] = {
                            "_rank": rank,
                            "mixed_old": any(w.mixed for w in mo),
                            "mixed_new": any(w.mixed for w in mn),
                            "shared_dates_old": sorted(
                                {d for w in mo for d in w.shared_dates})[:10],
                            "shared_dates_new": sorted(
                                {d for w in mn for d in w.shared_dates})[:10],
                            "signal": sg or ("old_only" if i is not None
                                             else "new_only"),
                            "dates_old": list(od[:dates_max]),
                            "dates_new": list(nd[:dates_max]),
                            "dates_old_total": len(od),
                            "dates_new_total": len(nd),
                            # 全日付からサーバー側でラン圧縮 (キャップ後の
                            # 圧縮だと「3/1〜3/30 ほか(全245日)」になる —
                            # しんぐうの実例)
                            "runs_old": ro, "runs_old_more": ro_more,
                            "runs_new": rn, "runs_new_more": rn_more,
                        }
            order = sorted(cell_meta, key=lambda ck: (
                ck[0][0] if ck[0] else "99999999",
                ck[1][0] if ck[1] else "99999999", ck))
            multi = len(order) > 1
            disp_of = {ck: (f"{label}@{idx}" if multi else label)
                       for idx, ck in enumerate(order, start=1)}
            gmeta = self.group_day_cells.setdefault(group, {})
            for ck, disp in disp_of.items():
                meta = dict(cell_meta[ck])
                meta.pop("_rank", None)
                if meta["dates_old_total"] or meta["dates_new_total"]:
                    gmeta[disp] = meta
            for direction, o_pats, n_pats, o_fams, n_fams, cells in entries:
                for i, j, sg in cells:
                    od = o_pats[i].dates if i is not None else ()
                    nd = n_pats[j].dates if j is not None else ()
                    disp = disp_of[(od, nd)]
                    if i is not None:
                        for k_, w in enumerate(o_pats[i].world_ids):
                            self._disp[("o", o_fams[i], direction, label, w)] = (
                                disp if k_ == 0 else _DUP)
                    if j is not None:
                        for k_, w in enumerate(n_pats[j].world_ids):
                            self._disp[("n", n_fams[j], direction, label, w)] = (
                                disp if k_ == 0 else _DUP)

    def _build_twins(self) -> None:
        wc = self.wc
        buckets: dict = defaultdict(list)
        for side, trips, w in (("o", self.delta.old_trips, wc.old),
                               ("n", self.delta.new_trips, wc.new)):
            for t in trips.values():
                if t.day_type in w.multi_labels:
                    buckets[(side, t.family, t.direction, t.day_type,
                             w.world_of(t.service_id))].append(t)

        def skey(t):
            return (t.times, t.base_seq, t.trip_id)

        for side, pats_map in (("o", wc.old_patterns), ("n", wc.new_patterns)):
            for (fam, direction, label), pats in pats_map.items():
                for pat in pats:
                    if len(pat.world_ids) < 2:
                        continue
                    rep = sorted(
                        buckets.get((side, fam, direction, label,
                                     pat.world_ids[0]), []), key=skey)
                    for w in pat.world_ids[1:]:
                        twins = sorted(
                            buckets.get((side, fam, direction, label, w), []),
                            key=skey)
                        for tw, tr in zip(twins, rep):
                            self._twin[(side, tw.trip_id)] = tr

    def _norm(self, side: str, t: TripInfo) -> TripInfo:
        """表示正規形: 非代表世界の便を代表世界の双子便に写す。"""
        return self._twin.get((side, t.trip_id), t)

    def _dlabel(self, side: str, t: TripInfo) -> str:
        """trip の表示上の day_type (セルラベル)。side: "o"/"n"。"""
        if self.wc is None:
            return t.day_type
        w = (self.wc.old if side == "o" else self.wc.new).world_of(t.service_id)
        return self._disp.get(
            (side, t.family, t.direction, t.day_type, w), t.day_type)

    def _coord(self, families, base: str) -> tuple[float, float] | None:
        """停留所座標の引き当て。当該路線 (family) を通るクラスタを優先する。"""
        for fam in families:
            xy = self.coords_family.get((fam, base))
            if xy:
                return xy
        return self.coords.get(base)

    @staticmethod
    def _seq_to_cluster(clusters) -> dict:
        m = {}
        for c in clusters:
            for p in c.patterns:
                m[(p.family, p.direction, p.base_names)] = c.cluster_id
        return m

    def build(self) -> dict:
        groups = sorted(
            {self.f2g.get(t.family, t.family)
             for t in list(self.delta.old_trips.values()) + list(self.delta.new_trips.values())
             if t.family}
        )
        pages = []
        for group in groups:
            page = self._build_page(group)
            if page:
                pages.append(page)
        # 変化のあるページを先に (Lev.1 > その他の変化 > 変化なし)、
        # ブロック内は路線名の自然順 (G4 — 全角/桁数で番号順が崩れない)
        pages.sort(key=lambda p: (0 if p["summary"]["level1"] else
                                  (1 if p["has_changes"] else 2),
                                  natural_sort_key(p["route_group"])))
        return {
            "day_type_order": DAY_ORDER,
            "route_pages": pages,
            "stop_changes": self._stop_changes(),
            # PI-1: 第1部「曜日区分ごとの便数」もここから取る (第3部と同じ
            # 表示便数 = 代表世界のみ・1日あたり)。bundle 側で再集計しない
            "day_type_totals": self._feed_day_totals(),
            "self_check": self.self_check,
        }

    def _feed_day_totals(self) -> list[dict]:
        """フィード全体の day_type 別表示便数 (基底ラベル集計)。

        第1部の便数表は従来 trip の生カウント (のべ) だったため、双子世界を
        束ねた第3部と矛盾する数字が出た (PRT 特定日 38→76 vs 38→38 —
        ui_quality.md A1)。_dlabel の表示射影を通し、重複世界 (_DUP) を除いて
        数える。mixed な世界を含む区分にはフラグを伝播する (PI-2)。"""
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for side, trips in (("o", self.delta.old_trips),
                            ("n", self.delta.new_trips)):
            for t in trips.values():
                dl = self._dlabel(side, t)
                if dl == _DUP:
                    continue
                counts[base_day(dl)][0 if side == "o" else 1] += 1
        mixed: dict[str, list[bool]] = defaultdict(lambda: [False, False])
        for gmeta in self.group_day_cells.values():
            for disp, meta in gmeta.items():
                b = base_day(disp)
                mixed[b][0] |= bool(meta.get("mixed_old"))
                mixed[b][1] |= bool(meta.get("mixed_new"))
        out = []
        for d in sorted(counts, key=day_sort_key):
            entry = {"day_type": d, "old": counts[d][0], "new": counts[d][1]}
            if mixed[d][0]:
                entry["mixed_old"] = True
            if mixed[d][1]:
                entry["mixed_new"] = True
            out.append(entry)
        return out

    # --- 停留所の変化 (V4: 路線に紐付かないレポート章) ---

    def _stop_changes(self) -> dict:
        """D群イベントを停留所クラスタ単位に集約したレポート章用ビュー。

        - 改称・移設は重要 → 1停留所1項目 (座標・影響路線付き)
        - 新設・廃止は路線廃止等で大量発生する → 影響 route_group の組ごとに
          まとめる (1事象1行にしない)
        - 乗り場 (PLATFORM_*) はマイナー扱い → 種類別件数に集約
        """
        old_by_name = {c.base_name: c for c in self.identity.old_stop_clusters.values()}
        new_by_name = {c.base_name: c for c in self.identity.new_stop_clusters.values()}

        def groups_of(name: str) -> list[str]:
            return sorted(self.stop_groups.get(name, ()))

        renamed = []
        relocated = []
        added_stops = []
        removed_stops = []
        platform: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for e in self.events:
            name = e.subject.get("stop_cluster", "")
            if e.type == "STOP_RENAMED":
                c = new_by_name.get(name)
                renamed.append({
                    "old_name": (e.old_ref or {}).get("name", ""),
                    "new_name": (e.new_ref or {}).get("name", name),
                    "lat": c.lat if c else None,
                    "lon": c.lon if c else None,
                    "groups": groups_of(name),
                })
            elif e.type == "STOP_RELOCATED":
                c_new = new_by_name.get(name)
                c_old = old_by_name.get(name)
                relocated.append({
                    "name": e.subject.get("name", name),
                    "moved_m": e.quantification.get("moved_m"),
                    "lat": c_new.lat if c_new else None,
                    "lon": c_new.lon if c_new else None,
                    "old_lat": c_old.lat if c_old else None,
                    "old_lon": c_old.lon if c_old else None,
                    "groups": groups_of(name),
                })
            elif e.type == "STOP_ADDED":
                c = new_by_name.get(name)
                added_stops.append({
                    "name": e.subject.get("name", name),
                    "lat": c.lat if c else None,
                    "lon": c.lon if c else None,
                    "groups": groups_of(name),
                })
            elif e.type == "STOP_REMOVED":
                c = old_by_name.get(name)
                removed_stops.append({
                    "name": e.subject.get("name", name),
                    "lat": c.lat if c else None,
                    "lon": c.lon if c else None,
                    "groups": groups_of(name),
                })
            elif e.type in ("PLATFORM_CHANGED", "PLATFORM_ADDED", "PLATFORM_REMOVED"):
                platform[name][e.type] += 1

        def group_bulk(stops: list[dict]) -> list[dict]:
            # 影響 route_group の組ごとにまとめる (路線廃止で一斉に消える停留所は1項目)
            buckets: dict[tuple, list[dict]] = defaultdict(list)
            for s in sorted(stops, key=lambda s: s["name"]):
                buckets[tuple(s["groups"])].append(s)
            return [
                {"groups": list(key), "stops": members}
                for key, members in sorted(buckets.items())
            ]

        return {
            "renamed": sorted(renamed, key=lambda r: r["old_name"]),
            "relocated": sorted(relocated, key=lambda r: r["name"]),
            "added": group_bulk(added_stops),
            "removed": group_bulk(removed_stops),
            "platform": [
                {"name": name, "kinds": dict(kinds)}
                for name, kinds in sorted(platform.items())
            ],
        }

    # --- ページ構築 ---

    def _group_trips(self, trips: dict[str, TripInfo], group: str) -> list[TripInfo]:
        return [t for t in trips.values() if self.f2g.get(t.family) == group]

    def _build_page(self, group: str) -> dict | None:
        old_trips = self._group_trips(self.delta.old_trips, group)
        new_trips = self._group_trips(self.delta.new_trips, group)
        if not old_trips and not new_trips:
            return None

        systems = self._systems(group, old_trips, new_trips)
        dgroups = self._direction_groups(systems)
        self._leg_views(dgroups)
        # 時刻表を先に構築し、表示用ペアリング (廃止×新設の組) を summary と共有する。
        # trip_id が張り替わるフィードでも Lev.3 / Lev.5 が経路・時刻変更を拾える
        # 便の対応付けはコア (trip matching v2) が担い、表示層の後付けペアリングは
        # 廃止した (docs/design/trip_matching.md)
        # SD5b: 表示正規形 — 対応・増減を双子写像で代表世界に写し、
        # 同じ代表便への重複写像は先勝ちで畳む (1世界系では恒等 = 従来どおり)。
        #
        # G2 (2026-07-28, kyoto_review.md §2): 表示正規形は次の2つの規則で
        # ヘッダ・③と同じ割付に整合する:
        #   (1) 対の成立条件 — 両端が**このページに割り付き、かつ同一表示セル**
        #       にある場合のみ対として表示する。ページ跨ぎ・セル跨ぎの対応
        #       (コアの検出としては正しい「便の移動」) は表示上分解する
        #   (2) 閉包 — ページの表示 trip のうち対に入らなかったものが、
        #       過不足なく廃止/新設列になる。ページ内の便の保存則
        #       (各便がちょうど1回現れる) を構成的に保証する
        # コアの対応・イベント・台帳は不変。旧実装は (1) が OR 条件 (片端でも
        # 当ページなら採用) で跨ぎ対の列が相手側の面に現れ、(2) がなく
        # delta.removed/added 由来のため分解された片端の受け皿が無かった
        # (京都 106 のヘッダ 10→5 vs ④ 5→5、市バス20 の新設ページに旧列)

        # 表示 trip 集合 (元の並び順を保存 — 1世界系で従来と同一の列順)
        display_old: list = []
        seen: set = set()
        for t in old_trips:
            t2 = self._norm("o", t)
            if t2.trip_id not in seen and self._dlabel("o", t2) != _DUP:
                seen.add(t2.trip_id)
                display_old.append(t2)
        display_new: list = []
        seen = set()
        for t in new_trips:
            t2 = self._norm("n", t)
            if t2.trip_id not in seen and self._dlabel("n", t2) != _DUP:
                seen.add(t2.trip_id)
                display_new.append(t2)

        disp_pairs: list = []  # (source, o2, n2)
        used_o: set = set()
        used_n: set = set()
        for source, pairs_src in (("exact", self.delta.exact_pairs),
                                  ("modified", self.delta.modified)):
            for o, nw in pairs_src:
                if (self.f2g.get(o.family) != group
                        or self.f2g.get(nw.family) != group):
                    continue  # 規則(1): ページ跨ぎの対は表示上分解
                o2, n2 = self._norm("o", o), self._norm("n", nw)
                if self._dlabel("o", o2) != self._dlabel("n", n2):
                    continue  # 規則(1): セル跨ぎの対は表示上分解
                if o2.trip_id in used_o or n2.trip_id in used_n:
                    continue
                used_o.add(o2.trip_id)
                used_n.add(n2.trip_id)
                disp_pairs.append((source, o2, n2))
        # 規則(2): 閉包
        disp_removed = [t for t in display_old if t.trip_id not in used_o]
        disp_added = [t for t in display_new if t.trip_id not in used_n]
        band_matrix = self._band_matrix(dgroups, display_old, display_new)
        timetables = self._timetables(dgroups, display_old, display_new,
                                      disp_pairs)

        # R19: 便ラベル (曜日別・ラベル別の件数)。素材はコアの対応付けのみ
        day_labels: dict[str, Counter] = defaultdict(Counter)
        for source, o2, n2 in disp_pairs:
            if source != "modified":
                continue
            dl = self._dlabel("n", n2)
            if dl != _DUP:
                day_labels[dl][trip_pair_label(o2, n2, self.retime_minor)] += 1
        for t2 in disp_removed:
            dl = self._dlabel("o", t2)
            if dl != _DUP:
                day_labels[dl]["removed"] += 1
        for t2 in disp_added:
            dl = self._dlabel("n", t2)
            if dl != _DUP:
                day_labels[dl]["added"] += 1
        label_totals: Counter = Counter()
        for c in day_labels.values():
            label_totals.update(c)

        summary = self._summary(group, dgroups, systems, band_matrix,
                                len(old_trips), len(new_trips), label_totals,
                                day_labels)

        has_changes = bool(
            summary["level1"] or summary["level2"] or summary["level3"]
            or summary["level4"] or summary["level5"]["retimed_minor"]
            or summary["level5"]["retimed_major"] or summary["level5"]["notes"]
        )
        # 曜日タブ用 (R18): 新旧いずれかに便がある day_type を固定順で列挙。
        # 廃止された運行日 (old>0, new=0) もタブに残す — 消えたこと自体が情報
        day_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for t in display_old:
            day_counts[self._dlabel("o", t)][0] += 1
        for t in display_new:
            day_counts[self._dlabel("n", t)][1] += 1
        day_totals = [
            {"day_type": d, "old": day_counts[d][0], "new": day_counts[d][1],
             # R19: 折りたたみチップ用のラベル別件数 (0件は出さない)
             "labels": {k: day_labels[d][k] for k in TRIP_LABEL_ORDER
                        if day_labels[d].get(k)}}
            for d in sorted(day_counts, key=day_sort_key)
        ]
        # 整合の不変条件 (presentation の台帳): ヘッダ (day_totals) の便数と
        # ④時刻表の列数合計が day_type ごとに一致する。便が ③④ から
        # 静かに消えるバグ (M9 の N:1 クラスタ崩落で実際に起きた) の再発防止
        tt_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for tb in timetables:
            tt_counts[tb["day_type"]][0] += tb["trips_old"]
            tt_counts[tb["day_type"]][1] += tb["trips_new"]
        for d, (n_old, n_new) in sorted(day_counts.items()):
            got = tt_counts.get(d, [0, 0])
            if [n_old, n_new] != list(got):
                logger.warning(
                    "presentation 整合エラー: %s %s ヘッダ %d→%d / ④ %d→%d",
                    group, d, n_old, n_new, got[0], got[1],
                )
                meta = self.group_day_cells.get(group, {}).get(d) or {}
                self.self_check.append({
                    "check": "header_vs_timetable",
                    "route_group": group, "day_type": d,
                    "header": [n_old, n_new], "timetable": list(got),
                    # 混成世界 (SD5c 案C) はヘッダが「のべ」・④が対応整列で、
                    # 数の不一致は設計上の既知差 — パネルではその旨を注記する
                    "mixed": bool(meta.get("mixed_old") or meta.get("mixed_new")),
                })
        # SD5c 案C: 混成世界セルのタブは「のべ便数」表記 (断定しない)
        for entry in day_totals:
            meta = self.group_day_cells.get(group, {}).get(entry["day_type"])
            if meta:
                if meta.get("mixed_old"):
                    entry["mixed_old"] = True
                if meta.get("mixed_new"):
                    entry["mixed_new"] = True

        # M10: 増便/限定型の注記。dow_* の曜日集合を包含する day_type の便が
        # **同じ世代で共存**する場合のみ「◯◯に追加」— 最小の上位集合
        # (同点は R16 順)。旧=平日 → 新=月水 のような運行日の変更
        # (共存しない) は追加ではないので注記しない
        from ..load.day_types import day_set_of

        def coexists(a: dict, b: dict) -> bool:
            return (a["old"] > 0 and b["old"] > 0) or (a["new"] > 0 and b["new"] > 0)

        for entry in day_totals:
            if not base_day(entry["day_type"]).startswith("dow_"):
                continue
            own = day_set_of(base_day(entry["day_type"]))
            covers = [
                (len(day_set_of(base_day(other["day_type"]))),
                 day_sort_key(other["day_type"]), other["day_type"])
                for other in day_totals
                if other is not entry and day_set_of(base_day(other["day_type"]))
                and own < day_set_of(base_day(other["day_type"]))
                and coexists(entry, other)
            ]
            if covers:
                entry["added_to"] = min(covers)[2]

        # M9: 旧名称 (対応した family) と、廃止/新設ページの類似候補注記
        former_names = sorted(self.former_by_group.get(group, ()))
        similar = []
        if summary["level1"]:
            source = (self.cand_old_group if summary["level1"]["kind"] == "removed"
                      else self.cand_new_group)
            seen = set()
            for conf, name in sorted(source.get(group, ()), key=lambda c: (-c[0], c[1])):
                if name not in seen:
                    seen.add(name)
                    similar.append({"name": name, "similarity": conf})
            similar = similar[:3]

        # 対応の取りこぼしの煙感知器 (orientation.md §4): 新設ページに旧名称や
        # 完全一致級 (類似度1.0) の候補が付くのは自己矛盾 — family 対応が
        # 前身を取り逃がしている (京都 20系・西系で実際に起きたクラス)。
        # 廃止側も対称に検知する
        if summary["level1"]:
            exact = [c["name"] for c in similar if c["similarity"] >= 1.0]
            kind = summary["level1"]["kind"]
            if (kind == "added" and (former_names or exact)) or (
                    kind == "removed" and exact):
                self.self_check.append({
                    "check": "level1_with_counterpart",
                    "route_group": group, "kind": kind,
                    "former_names": list(former_names),
                    "exact_candidates": exact,
                })

        return {
            "route_group": group,
            "families": sorted({t.family for t in old_trips + new_trips}),
            "former_names": former_names,
            "similar_candidates": similar,
            "has_changes": has_changes,
            "day_totals": day_totals,
            # SD5b: 表示セルのメタ (日付・対応信号)。1世界系では空
            "day_cells": self.group_day_cells.get(group, {}),
            "overview": {
                "trip_totals": {"old": len(old_trips), "new": len(new_trips)},
                "direction_groups": dgroups,
                # 主要停留所: 名前 → tier (1=起終点・ハブ / 2=系統端点・分岐点)。
                # 地図のズーム段階表示と路線概要の停車列省略の両方で共有する
                "key_stops": self._key_stops(group, dgroups),
            },
            "summary": summary,
            # R19: 一言ダイジェスト (優先順の事実 ≤3件、文章化はビューア i18n)
            "digest": self._digest(summary, day_totals, label_totals),
            "band_matrix": band_matrix,
            "timetables": timetables,
        }

    # --- 運行系統 (新旧クラスタの統合ビュー) ---

    def _systems(self, group, old_trips, new_trips) -> list[dict]:
        old_clusters = {
            c.cluster_id: c for c in self.identity.old_pattern_clusters
            if self.f2g.get(c.family) == group
        }
        new_clusters = {
            c.cluster_id: c for c in self.identity.new_pattern_clusters
            if self.f2g.get(c.family) == group
        }
        link = {}  # old_id → new_id (accept 以上の最良)
        for old_id in old_clusters:
            matches = self.identity.graph.matches_for_old(ENTITY_PATTERN_CLUSTER, old_id)
            if matches and matches[0].confidence >= self.accept \
                    and matches[0].new_id in new_clusters:
                link[old_id] = matches[0].new_id
        # M9 で family が統合されると複数の旧クラスタが同じ新クラスタに
        # リンクする (N:1)。1:1 前提で先頭以外を落とすと ③④ から便が
        # 静かに消えるため、旧クラスタは全てぶら下げる
        olds_by_new: dict[str, list[str]] = defaultdict(list)
        for o, n in sorted(link.items()):
            olds_by_new[n].append(o)

        def trips_of(trips, cluster, seq2cluster):
            return sum(
                1 for t in trips
                if seq2cluster.get((t.family, t.direction, t.base_seq)) == cluster
            )

        def earliest(cluster_olds, cluster_new):
            deps = [
                t.first_departure
                for t in old_trips
                if self.old_seq2cluster.get((t.family, t.direction, t.base_seq))
                in cluster_olds
            ] + [
                t.first_departure
                for t in new_trips
                if self.new_seq2cluster.get((t.family, t.direction, t.base_seq)) == cluster_new
            ]
            return min((d for d in deps if d), default="99:99:99")

        systems = []
        for new_id, c in sorted(new_clusters.items()):
            old_ids = olds_by_new.get(new_id, [])
            rep = c.representative
            systems.append({
                "system_id": new_id,
                "family": c.family,
                "direction": c.direction,
                "status": "continued" if old_ids else "added",
                "stops": list(rep.base_names),
                "first_stop": rep.base_names[0],
                "last_stop": rep.base_names[-1],
                "trips_old": sum(
                    trips_of(old_trips, oid, self.old_seq2cluster) for oid in old_ids
                ),
                "trips_new": trips_of(new_trips, new_id, self.new_seq2cluster),
                "old_system_id": old_ids[0] if old_ids else None,  # 代表 (互換)
                "old_system_ids": old_ids,
                "earliest_departure": earliest(set(old_ids), new_id),
                "polyline": [xy for s in rep.base_names
                             if (xy := self._coord((c.family,), s))],
            })
        for old_id, c in sorted(old_clusters.items()):
            if old_id in link:
                continue
            rep = c.representative
            systems.append({
                "system_id": f"old:{old_id}",
                "family": c.family,
                "direction": c.direction,
                "status": "removed",
                "stops": list(rep.base_names),
                "first_stop": rep.base_names[0],
                "last_stop": rep.base_names[-1],
                "trips_old": trips_of(old_trips, old_id, self.old_seq2cluster),
                "trips_new": 0,
                "old_system_id": old_id,
                "old_system_ids": [old_id],
                "earliest_departure": earliest({old_id}, None),
                "polyline": [xy for s in rep.base_names
                             if (xy := self._coord((c.family,), s))],
            })
        return systems

    # --- 方向グループ (R15: クラスタ由来、direction_id 非依存) ---

    def _direction_groups(self, systems: list[dict]) -> list[dict]:
        n = len(systems)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            parent[find(a)] = find(b)

        # R15 改訂 (2026-07-07): 端点完全一致は要求せず、共有停留所の順序整合度で
        # 往復 (<= reversed_max) / 同方向 (>= same_min) を判定。中間域は束ねない。
        for i in range(n):
            for j in range(i + 1, n):
                a, b = systems[i], systems[j]
                jac = stop_jaccard(set(a["stops"]), set(b["stops"]))
                if jac < self.pair_jaccard:
                    continue
                agree, shared = order_agreement(a["stops"], b["stops"])
                if agree is None or shared < self.min_shared:
                    continue
                if agree <= self.reversed_max or agree >= self.same_min:
                    union(i, j)

        by_root: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            by_root[find(i)].append(i)

        dgroups = []
        for members in by_root.values():
            group_systems = [systems[i] for i in members]
            # 代表 = 便数最多の系統。その向きを forward とする
            canon = min(
                group_systems,
                key=lambda s: (-(s["trips_new"] + s["trips_old"]),
                               s["earliest_departure"], s["system_id"]),
            )
            loop = canon["first_stop"] == canon["last_stop"]
            # G3 (orientation.md §5): 起点=終点 (循環) でも向きを問う —
            # 双方向路線と**同一の判定器 (order_agreement)・同一の閾値**で
            # 逆回り系統を reverse の leg に分ける。旧実装は循環を無条件に
            # forward へ畳み、③④地図の分割が面ごとにばらけていた
            # (京都 201〜208: ④は左右回り混在の1枚、③は識別不能な2行、地図1色)
            for s in group_systems:
                agree, _ = order_agreement(s["stops"], canon["stops"])
                s["leg"] = (
                    "reverse"
                    if agree is not None and agree <= self.reversed_max
                    else "forward"
                )
            has_reverse = any(s["leg"] == "reverse" for s in group_systems)
            if loop:
                kind, label = "loop", f"{canon['first_stop']} 循環"
            elif has_reverse:
                kind = "bidirectional"
                label = f"{canon['first_stop']} ⇄ {canon['last_stop']}"
            else:
                kind, label = "one_way", f"{canon['first_stop']} → {canon['last_stop']}"
            if loop and has_reverse:
                # 向き (B層) の名前: 起点→終点は循環では無意味 (A→A) なので、
                # 分冊と同じ「◯◯先回り」命名 — 各回りの代表停車列同士の
                # 最初の相違停留所。B/C/D で同じ語彙を共有する (kyoto_review G3)
                rev_canon = min(
                    (s for s in group_systems if s["leg"] == "reverse"),
                    key=lambda s: (-(s["trips_new"] + s["trips_old"]),
                                   s["earliest_departure"], s["system_id"]),
                )
                leg_labels = {
                    "forward": _loop_leg_label(
                        label, canon["first_stop"],
                        canon["stops"], rev_canon["stops"]),
                    "reverse": _loop_leg_label(
                        label, canon["first_stop"],
                        rev_canon["stops"], canon["stops"]),
                }
                if leg_labels["forward"] == leg_labels["reverse"]:
                    leg_labels["reverse"] += "（2）"
            else:
                # ④時刻表の表題・③本数表の方向行に共通で使う「起点 → 終点」
                # 形式 (dg ラベル「A ⇄ B」との対応が読み取れるように
                # 「◯◯方面」をやめた)。片回りのみの循環は従来どおり
                leg_labels = {
                    "forward": label if loop else
                    f"{canon['first_stop']} → {canon['last_stop']}",
                    "reverse": f"{canon['last_stop']} → {canon['first_stop']}",
                }
            dgroups.append({
                "id": "",  # 後で採番
                "kind": kind,
                "label": label,
                "leg_labels": leg_labels,
                "systems": sorted(group_systems,
                                  key=lambda s: (-s["trips_new"] - s["trips_old"],
                                                 s["system_id"])),
            })
        dgroups.sort(key=lambda g: -sum(s["trips_new"] + s["trips_old"]
                                        for s in g["systems"]))
        for i, g in enumerate(dgroups):
            g["id"] = f"dg{i}"
            for s in g["systems"]:
                s["direction_group"] = g["id"]
        return dgroups

    def _leg_views(self, dgroups: list[dict]) -> None:
        """①路線概要用の leg (時刻表単位・曜日統合) ビューを各 dg に付与する (R2 改)。

        - legs[].lines: 他パターンに完全包含されないパターン (極大パターン) のみ。
          区間便は線を増やさず、その端点は key_stops (tier2) の強調が受け持つ。
          同一 leg の極大パターン群は地図で同色・同レーンに重ね描きされ、
          幹線は1本に見え分岐点から枝が分かれる
        - legs[].axis: leg 内全パターン (新旧・全曜日) の LCS 併合軸
        - axis_rows: 停車列表示の行。復路軸が往路軸の完全な鏡像なら
          「A ⇄ B」1行に畳む (非対称往復は自動的に2行になり非対称が見える)
        """
        old_by_id = {c.cluster_id: c for c in self.identity.old_pattern_clusters}
        new_by_id = {c.cluster_id: c for c in self.identity.new_pattern_clusters}

        def patterns_of(s) -> set[tuple]:
            pats: set[tuple] = set()
            refs = []
            if s["system_id"].startswith("old:"):
                refs.append((old_by_id, s["old_system_id"]))
            else:
                refs.append((new_by_id, s["system_id"]))
                for oid in s.get("old_system_ids", []):
                    refs.append((old_by_id, oid))
            for table, cid in refs:
                c = table.get(cid)
                if c:
                    pats.update(tuple(p.base_names) for p in c.patterns)
            return pats

        for g in dgroups:
            legs = []
            for leg in ("forward", "reverse"):
                members = [s for s in g["systems"] if s["leg"] == leg]
                if not members:
                    continue
                pats: set[tuple] = set()
                for s in members:
                    pats.update(patterns_of(s))
                ordered = sorted(pats, key=lambda p: (-len(p), p))
                maximal = [
                    p for p in ordered
                    if not any(q != p and _is_subsequence(p, q) for q in ordered)
                ]
                statuses = {s["status"] for s in members}
                leg_families = sorted({s["family"] for s in members})
                lines = []
                for p in maximal:
                    pts = [(stop, *xy) for stop in p
                           if (xy := self._coord(leg_families, stop))]
                    if len(pts) < 2:
                        continue
                    lines.append({
                        "stops": [stop for stop, _, _ in pts],
                        "polyline": [[lat, lon] for _, lat, lon in pts],
                    })
                legs.append({
                    "leg": leg,
                    "label": g["leg_labels"][leg],
                    "axis": list(build_stop_axis(ordered)),
                    "status": ("removed" if statuses == {"removed"} else
                               "added" if statuses == {"added"} else "continued"),
                    "lines": lines,
                })
            g["legs"] = legs
            if (len(legs) == 2
                    and legs[0]["axis"] == list(reversed(legs[1]["axis"]))):
                # kind=pair は双方向 (停留所間は — で結ぶ)、leg は片方向 (→ で結ぶ)
                g["axis_rows"] = [
                    {"label": g["label"], "kind": "pair", "stops": legs[0]["axis"]}
                ]
            else:
                g["axis_rows"] = [
                    {"label": lg["label"], "kind": "leg", "stops": lg["axis"]}
                    for lg in legs
                ]

    def _key_stops(self, group: str, dgroups: list[dict]) -> dict[str, int]:
        """主要停留所の tier 判定 (決定的)。

        tier1: 方向グループ canonical の起終点、および hub_min_groups 以上の
               route_group が通る停留所 (ターミナル・中心市街地の近似)
        tier2: 全停車パターンの始終点 (区間便・便ごとの途中始終点を含む)、
               および分岐・合流点 (同一 leg 内で後続または先行の停留所が
               2種以上に分かれる点)。系統代表でなく**クラスタ内の全パターン**で
               判定する (類似パターンが1系統に束なっても端点・分岐を拾う)
        """
        tiers: dict[str, int] = {}

        def mark(stop: str, tier: int) -> None:
            if stop not in tiers or tier < tiers[stop]:
                tiers[stop] = tier

        cluster_by_id = {c.cluster_id: c
                         for c in (self.identity.old_pattern_clusters
                                   + self.identity.new_pattern_clusters)}

        for dg in dgroups:
            # canonical (ラベルの両端) は tier1
            for stop in (dg["systems"][0]["first_stop"], dg["systems"][0]["last_stop"]):
                mark(stop, 1)
            successors: dict[str, set[str]] = defaultdict(set)
            predecessors: dict[str, set[str]] = defaultdict(set)
            for sy in dg["systems"]:
                same_leg = sy["leg"] == dg["systems"][0]["leg"]
                patterns = []
                for cid in (sy["system_id"].removeprefix("old:"),
                            *sy.get("old_system_ids", [])):
                    cluster = cluster_by_id.get(cid)
                    if cluster:
                        patterns.extend(cluster.patterns)
                if not patterns:
                    patterns = [None]
                for pattern in patterns:
                    stops = list(pattern.base_names) if pattern else sy["stops"]
                    if not stops:
                        continue
                    mark(stops[0], 2)
                    mark(stops[-1], 2)
                    if not same_leg:
                        continue  # 分岐判定は同一 leg 内でのみ
                    for i in range(len(stops) - 1):
                        successors[stops[i]].add(stops[i + 1])
                        predecessors[stops[i + 1]].add(stops[i])
            for stop, nxt in successors.items():
                if len(nxt) >= 2:
                    mark(stop, 2)
            for stop, prv in predecessors.items():
                if len(prv) >= 2:
                    mark(stop, 2)

        # ネットワークハブ (このグループ以外も含め hub_min_groups 路線以上が通る)
        group_stops = {s for dg in dgroups for sy in dg["systems"] for s in sy["stops"]}
        for stop in group_stops:
            if len(self.stop_groups.get(stop, ())) >= self.hub_min_groups:
                mark(stop, 1)
        return dict(sorted(tiers.items()))

    # --- ③ 本数マトリクス (R3, R14 の土台) ---

    def _band_matrix(self, dgroups, old_trips, new_trips) -> dict:
        sys_by_old_cluster = {}
        sys_by_new_cluster = {}
        for g in dgroups:
            for s in g["systems"]:
                for oid in s.get("old_system_ids", []):
                    sys_by_old_cluster[oid] = s
                if not s["system_id"].startswith("old:"):
                    sys_by_new_cluster[s["system_id"]] = s

        def system_for(trip: TripInfo, gen: str):
            if gen == "old":
                cid = self.old_seq2cluster.get((trip.family, trip.direction, trip.base_seq))
                return sys_by_old_cluster.get(cid)
            cid = self.new_seq2cluster.get((trip.family, trip.direction, trip.base_seq))
            return sys_by_new_cluster.get(cid)

        # (dg, day, system_id, band) → [old, new]
        cells: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        days = set()
        for trips, side, gen in ((old_trips, 0, "old"), (new_trips, 1, "new")):
            for t in trips:
                s = system_for(t, gen)
                if s is None:
                    continue
                band = self.bands.band_of(t.first_departure)
                dl = self._dlabel("o" if gen == "old" else "n", t)
                cells[(s["direction_group"], dl, s["system_id"], band)][side] += 1
                days.add(dl)

        band_labels = self.bands.labels()
        rows = []
        for g in dgroups:
            # 行の入れ子 (R3 改 2026-07-07): 方向グループ集計 → 方向 (leg) 集計 →
            # 系統内訳。leg 行は④時刻表と同じラベル・同じ便数になり対応が読める。
            # 方向が1つしかないグループ (one_way/loop) では leg 行は集計行と同じ
            # なので出さない
            multi_leg = len({s["leg"] for s in g["systems"]}) > 1
            for day in sorted(days, key=day_sort_key):
                agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
                leg_aggs: dict[str, dict[str, list[int]]] = {}
                leg_sys_rows: dict[str, list[dict]] = {}
                for s in g["systems"]:
                    row_cells = {}
                    for band in band_labels:
                        v = cells.get((g["id"], day, s["system_id"], band))
                        if v:
                            row_cells[band] = v
                            agg[band][0] += v[0]
                            agg[band][1] += v[1]
                            la = leg_aggs.setdefault(
                                s["leg"], defaultdict(lambda: [0, 0]))
                            la[band][0] += v[0]
                            la[band][1] += v[1]
                    if row_cells:
                        total = [sum(v[0] for v in row_cells.values()),
                                 sum(v[1] for v in row_cells.values())]
                        leg_sys_rows.setdefault(s["leg"], []).append({
                            "kind": "system",
                            "direction_group": g["id"],
                            "day_type": day,
                            "system_id": s["system_id"],
                            "label": f"{s['first_stop']}→{s['last_stop']}",
                            "leg": s["leg"],
                            "cells": row_cells,
                            "total": total,
                            "changed": total[0] != total[1]
                            or any(v[0] != v[1] for v in row_cells.values()),
                        })
                if not leg_sys_rows:
                    continue
                agg_total = [sum(v[0] for v in agg.values()),
                             sum(v[1] for v in agg.values())]
                rows.append({
                    "kind": "aggregate",
                    "direction_group": g["id"],
                    "day_type": day,
                    "label": g["label"],
                    "cells": dict(agg),
                    "total": agg_total,
                    "changed": any(v[0] != v[1] for v in agg.values()),
                })
                for leg in ("forward", "reverse"):
                    sys_rows = leg_sys_rows.get(leg)
                    if not sys_rows:
                        continue
                    if multi_leg:
                        la = leg_aggs[leg]
                        rows.append({
                            "kind": "leg",
                            "direction_group": g["id"],
                            "day_type": day,
                            "leg": leg,
                            "label": g["leg_labels"][leg],
                            "cells": dict(la),
                            "total": [sum(v[0] for v in la.values()),
                                      sum(v[1] for v in la.values())],
                            "changed": any(v[0] != v[1] for v in la.values()),
                        })
                    # 系統1つの階層では内訳行は冗長なので出さない
                    if len(sys_rows) > 1:
                        rows.extend(sys_rows)
        return {"bands": band_labels, "rows": rows}

    # --- ② 変化サマリー (R12 カスケード) ---

    def _summary(self, group, dgroups, systems, band_matrix, n_old, n_new,
                 label_totals, day_labels) -> dict:
        empty5 = {"retimed_minor": 0, "retimed_major": 0,
                  "minor_max_min": self.retime_minor, "notes": []}
        # Lev.1
        level1 = None
        if n_old == 0 and n_new > 0:
            level1 = {"kind": "added", "trips": n_new}
        elif n_new == 0 and n_old > 0:
            level1 = {"kind": "removed", "trips": n_old}
        if level1:
            return {"level1": level1, "level2": [], "level3": [],
                    "level4": [], "level5": empty5}

        # Lev.2: 系統の出現・消滅 (min_trips 以上)
        level2 = []
        lev2_system_ids = set()
        for s in systems:
            if s["status"] == "added" and s["trips_new"] >= self.min_trips:
                level2.append({"kind": "system_added", "system_id": s["system_id"],
                               "label": f"{s['first_stop']}→{s['last_stop']}",
                               "trips": s["trips_new"], "family": s["family"]})
                lev2_system_ids.add(s["system_id"])
            elif s["status"] == "removed" and s["trips_old"] >= self.min_trips:
                level2.append({"kind": "system_removed", "system_id": s["system_id"],
                               "label": f"{s['first_stop']}→{s['last_stop']}",
                               "trips": s["trips_old"], "family": s["family"]})
                lev2_system_ids.add(s["system_id"])

        # Lev.3: 経由停変化ユニット (影響率 R13)。素材は modified + 表示ペアリング
        level3 = self._level3_units(group, systems, lev2_system_ids)

        # Lev.4: 増減便 = 便ラベルの added / removed 件数 (R14 改訂 2026-07-10)。
        # 旧定義「ビン別本数差分の符号別合計」は M8 以前 (便対応が不確か) の
        # 頑健策で、対応付けが内容主導になった今は
        # (a) 同一時間帯の本当の廃止+新設を相殺し (b) 時間帯を跨ぐ時刻変更を
        # 増減として二重計上して、④の 新/廃 マークと矛盾した (朝日町の実例)。
        # ラベル由来なら ヘッダ・④・ダイジェストと構造的に一致する
        # (net = 新旧便数差 = added − removed。ビン別の内訳は③が担う)
        level4 = [
            {"day_type": d,
             "net": day_labels[d].get("added", 0) - day_labels[d].get("removed", 0),
             "increased": day_labels[d].get("added", 0),
             "decreased": day_labels[d].get("removed", 0)}
            for d in sorted(day_labels, key=day_sort_key)
            if day_labels[d].get("added") or day_labels[d].get("removed")
        ]

        notes = []
        shape_events = [
            e for e in self.events
            if e.type == "SHAPE_CHANGED" and e.quantification.get("significant")
            and group in {self.f2g.get(f, f) for f in e.subject.get("route_families", [])}
        ]
        if shape_events:
            notes.append({"kind": "shape_changed", "count": len(shape_events)})
        headsign = [
            e for e in self.events
            if e.type == "HEADSIGN_CHANGED"
            and self.f2g.get(e.subject.get("route_family", "")) == group
        ]
        if headsign:
            notes.append({"kind": "headsign_changed",
                          "count": sum(e.quantification.get("changed_fields", 1)
                                       for e in headsign)})
        # Lev.5: 時刻のみの変化 (R19: 便ラベルの集計から。微調整と閾値超を分ける)
        level5 = dict(empty5, retimed_minor=label_totals.get("retimed_minor", 0),
                      retimed_major=label_totals.get("retimed", 0), notes=notes)
        return {"level1": None, "level2": level2, "level3": level3,
                "level4": level4, "level5": level5}

    def _digest(self, summary, day_totals, label_totals) -> list[dict]:
        """一言ダイジェスト (R19)。

        折りたたみ表示と②冒頭で共通に使う「この改正を一言で」の素材。
        事実を優先順位 (路線新廃 > 系統再編 > 経路系 > 便数増減 > 時刻系) で
        選び上位3件を構造化して返す。文章化は i18n (ビューア) 側 —
        bundle は言語中立 (docs/design/web.md)。
        """
        if summary["level1"]:
            return [{"kind": "route_" + summary["level1"]["kind"],
                     "trips": summary["level1"]["trips"]}]
        facts = []
        if summary["level2"]:
            added = sum(1 for x in summary["level2"] if x["kind"] == "system_added")
            facts.append({"kind": "systems", "added": added,
                          "removed": len(summary["level2"]) - added})
        n_route = sum(label_totals.get(k, 0)
                      for k in ("rerouted", "shortened", "extended"))
        if n_route:
            facts.append({"kind": "reroute", "trips": n_route})
        # PI-2: mixed (のべ便数) の区分は増減を断定できないのでダイジェスト対象外。
        # ⚠注記と のべ表記はタブ側が受け持つ
        changed_days = [d for d in day_totals if d["old"] != d["new"]
                        and not (d.get("mixed_old") or d.get("mixed_new"))]
        if changed_days:
            facts.append({"kind": "trips", "days": [
                {"day_type": d["day_type"], "old": d["old"], "new": d["new"]}
                for d in changed_days]})
        if label_totals.get("retimed"):
            facts.append({"kind": "retime", "trips": label_totals["retimed"],
                          "minor_max_min": self.retime_minor})
        elif label_totals.get("retimed_minor"):
            facts.append({"kind": "retime_minor",
                          "trips": label_totals["retimed_minor"]})
        if not facts and summary["level5"]["notes"]:
            # 便・便数に変化がなく shape / headsign のみの路線 (最低優先の受け皿)
            counts = {n["kind"]: n["count"] for n in summary["level5"]["notes"]}
            facts.append({"kind": "notes_only",
                          "shape": counts.get("shape_changed", 0),
                          "headsign": counts.get("headsign_changed", 0)})
        return facts[:3]

    def _level3_units(self, group, systems, lev2_ids) -> list[dict]:
        """経由停変化ユニット。

        素材は trip 単位の新旧対応: (a) trip_delta.modified (同一 trip_id) と
        (b) 時刻表の表示用ペアリングで組めた対 (trip_id が張り替わるフィード)。
        B群イベント経由にしない (direction_id の無いフィードではイベントが
        両方向を1件に束ねるため、系統への帰属が不正確になる)。
        検出の正当性は B群イベント (説明台帳) が担保し、ここは表示用の再集計。
        """
        # 系統の解決は ④時刻表と同じ機構 (seq2cluster → system) に統一する。
        # 旧実装は「代表パターンの停車列の完全一致」で、対のパターンが代表と
        # 違うと解決に失敗し、フォールバックの加算で分母が壊れた
        # (朝日町 南保線で 3/6 — ページ総便数を超える分母。2026-07-10 修正)
        sys_by_new_cluster: dict[str, dict] = {}
        sys_by_old_cluster: dict[str, dict] = {}
        for s in systems:
            if not s["system_id"].startswith("old:"):
                sys_by_new_cluster[s["system_id"]] = s
            for oid in s.get("old_system_ids", []):
                sys_by_old_cluster[oid] = s

        units: dict[tuple, dict] = {}
        for old_t, new_t in self.delta.modified:
            if self.f2g.get(new_t.family) != group or old_t.base_seq == new_t.base_seq:
                continue
            key = (new_t.family, new_t.direction, old_t.base_seq, new_t.base_seq)
            unit = units.setdefault(key, {
                "family": new_t.family,
                "affected": 0,
                "old_pattern": list(old_t.base_seq),
                "new_pattern": list(new_t.base_seq),
                "_new_cluster": self.new_seq2cluster.get(
                    (new_t.family, new_t.direction, new_t.base_seq)
                ),
                "_old_cluster": self.old_seq2cluster.get(
                    (old_t.family, old_t.direction, old_t.base_seq)
                ),
            })
            unit["affected"] += 1

        # 第2段階マージ: 人が認識する変化の単位 = (追加停留所集合, 削除停留所集合)。
        # 方向・系統・変形の種類 (延伸/挿入/迂回) の違いは「対象系統の内訳」に降格する
        # (一般ルール。豊前市の実例: 上り下り×複数パターン対が同一の追加/削除集合に束なる)
        merged: dict[tuple, dict] = {}
        for (family, direction, old_p, new_p), unit in sorted(units.items(), key=str):
            system = sys_by_new_cluster.get(unit["_new_cluster"]) \
                or sys_by_old_cluster.get(unit["_old_cluster"])
            affected = unit["affected"]
            total = (system["trips_new"] or system["trips_old"]) if system else affected
            added = set(new_p) - set(old_p)
            removed = set(old_p) - set(new_p)
            key = (tuple(sorted(added)), tuple(sorted(removed)))
            m = merged.setdefault(key, {
                "added_stops": sorted(added),
                "removed_stops": sorted(removed),
                "systems": [],
                "affected_trips": 0,
                "system_trips": 0,
                "_seen_systems": set(),
            })
            m["systems"].append({
                "system_id": system["system_id"] if system else None,
                "label": (f"{system['first_stop']}→{system['last_stop']}"
                          if system else family),
                "family": family,
                "leg": system.get("leg", "") if system else "",
                "affected_trips": affected,
                "system_trips": total,
                "old_pattern": unit["old_pattern"],
                "new_pattern": unit["new_pattern"],
            })
            m["affected_trips"] += affected
            if system and system["system_id"] not in m["_seen_systems"]:
                m["_seen_systems"].add(system["system_id"])
                m["system_trips"] += total
            elif not system:
                m["system_trips"] += total

        result = []
        for key in sorted(merged, key=str):
            m = merged[key]
            seen_systems = m.pop("_seen_systems")
            total = m["system_trips"]
            m["coverage"] = round(m["affected_trips"] / total, 3) if total else None
            m["full_coverage"] = bool(
                total and m["affected_trips"] / total >= self.full_coverage
            )
            m["absorbed_into_level2"] = bool(
                seen_systems and seen_systems <= lev2_ids
            )
            result.append(m)
        return result

    # --- ④ 新旧時刻表 (R17) ---

    def _timetables(self, dgroups, old_trips, new_trips,
                    disp_pairs=()) -> list[dict]:
        sys_by_old = {}
        sys_by_new = {}
        for g in dgroups:
            for s in g["systems"]:
                for oid in s.get("old_system_ids", []):
                    sys_by_old[oid] = s
                if not s["system_id"].startswith("old:"):
                    sys_by_new[s["system_id"]] = s

        def locate(trip: TripInfo, gen: str):
            if gen == "old":
                cid = self.old_seq2cluster.get((trip.family, trip.direction, trip.base_seq))
                return sys_by_old.get(cid)
            cid = self.new_seq2cluster.get((trip.family, trip.direction, trip.base_seq))
            return sys_by_new.get(cid)

        # trip 対応 (差分表示の素材)
        pair_of_old: dict[str, tuple[str, TripInfo, TripInfo]] = {}
        pair_of_new: dict[str, tuple[str, TripInfo, TripInfo]] = {}
        # SD5b: 対応は表示正規形 (双子写像・先勝ち畳み済み) から張る。
        # disp_pairs 未指定 (直接呼び出し) は従来どおり delta から
        if not disp_pairs:
            disp_pairs = (
                [("exact", o, nw) for o, nw in self.delta.exact_pairs]
                + [("modified", o, nw) for o, nw in self.delta.modified])
        for source, o, nw in disp_pairs:
            if source == "exact":
                status = "unchanged" if o.trip_id == nw.trip_id else "id_changed"
            else:
                status = "retimed" if o.base_seq == nw.base_seq else "rerouted"
            pair_of_old[o.trip_id] = (status, o, nw)
            pair_of_new[nw.trip_id] = (status, o, nw)

        # (dg, leg, day) → trips
        buckets: dict[tuple, dict] = defaultdict(lambda: {"old": [], "new": []})
        for t in old_trips:
            s = locate(t, "old")
            if s:
                buckets[(s["direction_group"], s["leg"],
                         self._dlabel("o", t))]["old"].append(t)
        for t in new_trips:
            s = locate(t, "new")
            if s:
                buckets[(s["direction_group"], s["leg"],
                         self._dlabel("n", t))]["new"].append(t)

        dg_label = {}
        for g in dgroups:
            for leg, label in g["leg_labels"].items():
                dg_label[(g["id"], leg)] = label

        tables = []
        max_sheet_cost = self.config.get(
            "presentation", "sheet_merge_max_gap_per_trip", default=0.5
        )
        split_trigger = self.config.get(
            "presentation", "sheet_split_trigger_gap_per_trip", default=1.5
        )
        for (dg, leg, day) in sorted(buckets, key=lambda k: (k[0], k[1], day_sort_key(k[2]))):
            bucket = buckets[(dg, leg, day)]
            # 列候補 (status, old, new) を作り、一意な停車パターンごとにまとめる
            # (経由違いは同一クラスタ内でも起こるため、初期単位は系統でなくパターン。
            #  包含・微差のパターンは併合コスト 0〜微小で自然に再併合される)
            specs_by_pattern: dict[tuple, list[tuple]] = defaultdict(list)

            done_old = set()
            for nw in bucket["new"]:
                pair = pair_of_new.get(nw.trip_id)
                if pair:
                    status, o, _ = pair
                    done_old.add(o.trip_id)
                else:
                    status, o = "added", None
                specs_by_pattern[nw.base_seq].append((status, o, nw))
            for o in bucket["old"]:
                if o.trip_id in done_old or o.trip_id in pair_of_old:
                    # 対応先が別バケット (経路変更で系統移動) の場合も旧側は出さない
                    continue
                specs_by_pattern[o.base_seq].append(("removed", o, None))
            if not specs_by_pattern:
                # 旧側の便がすべて別バケットへ対応付いた場合など。空テーブルは出さない
                continue

            # 分冊 (R17 改) はトップダウン: まず1枚で作り、読みにくい
            # (飛び/便 > トリガー閾値) ときだけパターン単位から束ね直す。
            # 読める表は分冊しない = 現状うまくいっている表は一切変わらない
            all_specs = [s for k in sorted(specs_by_pattern)
                         for s in specs_by_pattern[k]]
            avg_gap = _specs_gap(all_specs) / max(_specs_alignments(all_specs), 1)
            if avg_gap <= split_trigger:
                sheets = [all_specs]
            else:
                sheets = group_sheets(
                    [specs_by_pattern[k] for k in sorted(specs_by_pattern)],
                    max_sheet_cost,
                )
            sheets.sort(key=lambda sp: (-len(sp), _sheet_sort_key(sp)))
            labels = sheet_labels(sheets)
            for sheet_no, (specs, sheet_label) in enumerate(zip(sheets, labels)):
                # 軸は経路変更 trip の旧停車列も含めた超列にする
                # (差分表示で旧時刻も並べるため)
                seqs = set()
                for _, o, nw in specs:
                    for t in (o, nw):
                        if t is not None:
                            seqs.add(t.base_seq)
                axis = build_stop_axis(sorted(seqs))
                columns = [self._column(status, o, nw, axis)
                           for status, o, nw in specs]
                columns = sort_timetable_columns(columns)
                for c in columns:
                    del c["sort_key"]
                # R19: 折りたたみ行用の便数 (旧→新) とラベル別件数
                label_counts: Counter = Counter()
                trips_old = trips_new = 0
                for status, o, nw in specs:
                    # G2: 対の両端が同一セルにあることは表示正規形が保証する
                    # (跨ぎ対は閉包で廃止/新設列に分解済み)。系統 (leg) 移動の
                    # 対は移動先の表に旧時刻ごと現れ、ここで両側を数える
                    trips_old += o is not None
                    trips_new += nw is not None
                    if status in ("added", "removed"):
                        label_counts[status] += 1
                    elif status in ("retimed", "rerouted"):
                        label_counts[trip_pair_label(o, nw, self.retime_minor)] += 1
                    else:  # unchanged / id_changed
                        label_counts["unchanged"] += 1
                tables.append({
                    "direction_group": dg,
                    "leg": leg,
                    "label": dg_label.get((dg, leg), ""),
                    "sheet": sheet_no,
                    "sheet_label": sheet_label,
                    "day_type": day,
                    "trips_old": trips_old,
                    "trips_new": trips_new,
                    "label_counts": {k: label_counts[k] for k in TRIP_LABEL_ORDER
                                     if label_counts.get(k)},
                    "stop_axis": list(axis),
                    # both / old_only (廃止) / new_only (新設) —
                    # 行名の表示と ・・ 判定に使う
                    "stop_axis_status": [
                        "both" if (stop in self.old_stop_names
                                   and stop in self.new_stop_names)
                        else ("old_only" if stop in self.old_stop_names
                              else "new_only")
                        for stop in axis
                    ],
                    "columns": columns,
                })
        return tables

    @staticmethod
    def _times_on_axis(trip: TripInfo, axis) -> list[str | None]:
        """軸上の時刻列。None = その便の経路外、"" = 経路上だが時刻なし (通過)。"""
        row: list[str | None] = [None] * len(axis)
        for pos, (arr, dep) in zip(align_to_axis(trip.base_seq, axis), trip.times):
            if pos >= 0:
                row[pos] = dep or arr or ""
        return row

    @staticmethod
    def _minute(value: str | None) -> int | None:
        """表示粒度 (分) での時刻。None/空/不正は None。"""
        from ..events.timebands import parse_gtfs_time

        if not value:
            return None
        sec = parse_gtfs_time(value)
        return sec // 60 if sec is not None else None

    def _column(self, status, old: TripInfo | None, new: TripInfo | None, axis) -> dict:
        times_old = self._times_on_axis(old, axis) if old else None
        times_new = self._times_on_axis(new, axis) if new else None
        changed = []
        if times_old and times_new:
            # 表示粒度 (分) で比較する。秒だけの差は表示が変わらないため変更扱いしない
            changed = [
                i for i, (a, b) in enumerate(zip(times_old, times_new))
                if self._minute(a) != self._minute(b)
            ]
        ref = new or old
        return {
            "status": status,  # unchanged / id_changed / retimed / rerouted / added / removed
            "trip_id_old": old.trip_id if old else None,
            "trip_id_new": new.trip_id if new else None,
            "times_old": times_old,
            "times_new": times_new,
            "changed_positions": changed,
            "sort_key": ref.first_departure or "99:99:99",
        }
