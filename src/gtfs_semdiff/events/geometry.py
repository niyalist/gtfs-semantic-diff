"""ポリライン幾何ユーティリティ (SHAPE_CHANGED 判定用)。

座標は (lat, lon)。距離計算は対象範囲が数十 km 以下のため
等長方形近似 (equirectangular) で十分な精度が出る。
"""

from __future__ import annotations

import math

_EARTH_R = 6371000.0


def _project(points: list[tuple[float, float]], lat0: float) -> list[tuple[float, float]]:
    """(lat, lon) → 近似平面座標 (メートル)。"""
    k = math.cos(math.radians(lat0))
    return [
        (math.radians(lat) * _EARTH_R, math.radians(lon) * _EARTH_R * k)
        for lat, lon in points
    ]


def downsample(points: list[tuple[float, float]], max_points: int) -> list[tuple[float, float]]:
    """端点を保持しつつ最大 max_points 点に間引く。"""
    n = len(points)
    if n <= max_points:
        return points
    step = (n - 1) / (max_points - 1)
    return [points[round(i * step)] for i in range(max_points)]


def discrete_frechet_m(
    a: list[tuple[float, float]], b: list[tuple[float, float]]
) -> float:
    """離散 Fréchet 距離 (メートル)。空入力は inf。"""
    if not a or not b:
        return float("inf")
    lat0 = a[0][0]
    pa, pb = _project(a, lat0), _project(b, lat0)
    m, n = len(pa), len(pb)
    prev = [0.0] * n
    for i in range(m):
        cur = [0.0] * n
        xi, yi = pa[i]
        for j in range(n):
            xj, yj = pb[j]
            d = math.hypot(xi - xj, yi - yj)
            if i == 0 and j == 0:
                cur[j] = d
            elif i == 0:
                cur[j] = max(cur[j - 1], d)
            elif j == 0:
                cur[j] = max(prev[j], d)
            else:
                cur[j] = max(min(prev[j], prev[j - 1], cur[j - 1]), d)
        prev = cur
    return prev[n - 1]


def max_deviation(
    a: list[tuple[float, float]], b: list[tuple[float, float]]
) -> tuple[float, tuple[float, float] | None]:
    """a の各点から b への最近点距離の最大値と、その位置 (旧経路上の点)。"""
    if not a or not b:
        return float("inf"), None
    lat0 = a[0][0]
    pa, pb = _project(a, lat0), _project(b, lat0)
    worst = -1.0
    worst_idx = 0
    for i, (xi, yi) in enumerate(pa):
        nearest = min(math.hypot(xi - xj, yi - yj) for xj, yj in pb)
        if nearest > worst:
            worst = nearest
            worst_idx = i
    return worst, a[worst_idx]
