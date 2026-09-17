"""XL2: 投入前の規模プリフライト (infra/runtime/preflight.py) の単体テスト。

zip の central directory から stop_times 非圧縮サイズを読み、上限超過を
投入前に ja/en で断る純ロジック。boto3 非依存 (S3 つなぎは handler 側)。
"""
from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "web_preflight",
    Path(__file__).resolve().parent.parent / "infra" / "runtime" / "preflight.py",
)
preflight = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(preflight)

LIMIT = 150


def _zip_bytes(members: dict[str, int]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, mb in members.items():
            zf.writestr(name, b"a" * (mb * 1048576))
    buf.seek(0)
    return buf


def test_zip_scale_reads_stop_times_size():
    scale = preflight.zip_scale_mb(_zip_bytes({"stop_times.txt": 3, "stops.txt": 1}))
    assert scale == {"stop_times": 3, "total": 4}


def test_zip_scale_subdirectory_and_missing():
    # サブディレクトリ格納 (実データで存在) も、stop_times 無しも読める
    scale = preflight.zip_scale_mb(_zip_bytes({"gtfs/stop_times.txt": 2}))
    assert scale == {"stop_times": 2, "total": 2}
    assert preflight.zip_scale_mb(_zip_bytes({"stops.txt": 1}))["stop_times"] == 0


def test_zip_scale_unreadable_returns_none():
    assert preflight.zip_scale_mb(io.BytesIO(b"not a zip")) is None


def test_gate_blocks_oversized_with_bilingual_message():
    msg = preflight.gate_message(
        {"old": {"stop_times": 999, "total": 1200},
         "new": {"stop_times": 10, "total": 20}}, LIMIT)
    assert msg is not None
    ja, en = msg
    assert "999MB" in ja and "CLI" in ja and "150MB" in ja
    assert "999MB" in en and "CLI" in en and "developers.html" in en


def test_gate_passes_small_and_unknown():
    assert preflight.gate_message(
        {"old": {"stop_times": 149, "total": 500}, "new": None}, LIMIT) is None


def test_failure_message_names_size_when_near_limit():
    ja, en, kind = preflight.failure_message({"old": 140, "new": 145}, LIMIT)
    assert kind == "input"
    assert "145MB" in ja and "CLI" in ja
    assert "145MB" in en and "developers.html" in en
    # OOM か timeout かは断定しない
    assert "メモリ" in ja and "memory" in en


def test_failure_message_generic_when_small():
    ja, en, kind = preflight.failure_message({}, LIMIT)
    assert kind is None
    assert "再試行" in ja and "retry" in en.lower()
