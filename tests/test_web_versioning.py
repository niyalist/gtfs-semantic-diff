"""infra/runtime/versioning.py (W3-2a 正準 URL と版管理の純ロジック) の単体テスト。

boto3 非依存のモジュールなので、リポジトリ相対パスから直接読み込む。
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "web_versioning",
    Path(__file__).resolve().parent.parent / "infra" / "runtime" / "versioning.py",
)
versioning = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(versioning)

UID_A = "b1be1add-3553-4b31-86bc-348479c25526"
UID_B = "17ab34e1-dcb8-4b2e-9cda-ae2b68f4c444"


# --- pair キー ---


def test_pair_id_is_deterministic_and_uid_based():
    pair = versioning.pair_id("nagai-unyu", "Nagaibus", UID_A, UID_B)
    assert pair == "nagai-unyu__Nagaibus__b1be1add__17ab34e1"
    # 新旧の向きが違えば別ペア
    assert pair != versioning.pair_id("nagai-unyu", "Nagaibus", UID_B, UID_A)


def test_keys_layout():
    pair = "org__feed__aaaaaaaa__bbbbbbbb"
    assert versioning.entry_key(pair) == f"r/{pair}.html"
    assert versioning.version_key(pair, "2026.7.11.1") == f"r/{pair}/v/2026.7.11.1.html"
    assert versioning.index_key(pair) == f"r/{pair}/index.json"


def test_safe_uid_rejects_injection():
    with pytest.raises(ValueError):
        versioning.safe_uid("../etc/passwd")
    with pytest.raises(ValueError):
        versioning.safe_uid("")
    with pytest.raises(ValueError):
        versioning.safe_uid("zz not hex")


# --- 版の比較 ---


def test_parse_version_orders_calver():
    pv = versioning.parse_version
    assert pv("2026.7.11.1") > pv("2026.7.11")  # 旧3要素形式は N=0 扱い
    assert pv("2026.7.11.2") > pv("2026.7.11.1")
    assert pv("2026.10.1.1") > pv("2026.9.30.5")  # 文字列比較でなく数値比較
    assert pv("2027.1.1.1") > pv("2026.12.31.9")


# --- index.json (版台帳) ---


def test_update_index_first_version():
    idx = versioning.update_index(
        None, pair="p", version="2026.7.11.1", generated_at="T1",
        feed_info={"org": "o", "feed": "f"},
    )
    assert idx["latest"] == "2026.7.11.1"
    assert [v["version"] for v in idx["versions"]] == ["2026.7.11.1"]
    assert idx["versions"][0]["key"] == "r/p/v/2026.7.11.1.html"
    assert idx["feed"] == {"org": "o", "feed": "f"}


def test_update_index_appends_and_tracks_latest():
    idx = versioning.update_index(
        None, pair="p", version="2026.7.11.1", generated_at="T1")
    idx = versioning.update_index(
        idx, pair="p", version="2026.8.1.1", generated_at="T2")
    assert idx["latest"] == "2026.8.1.1"
    assert [v["version"] for v in idx["versions"]] == ["2026.8.1.1", "2026.7.11.1"]


def test_update_index_out_of_order_does_not_regress_latest():
    """ロールバック運用中に旧版を再生成しても latest は最大版のまま。"""
    idx = versioning.update_index(
        None, pair="p", version="2026.8.1.1", generated_at="T1")
    idx = versioning.update_index(
        idx, pair="p", version="2026.7.11.1", generated_at="T2")
    assert idx["latest"] == "2026.8.1.1"


def test_update_index_same_version_is_idempotent():
    idx = versioning.update_index(
        None, pair="p", version="2026.7.11.1", generated_at="T1")
    idx = versioning.update_index(
        idx, pair="p", version="2026.7.11.1", generated_at="T2")
    assert len(idx["versions"]) == 1
    assert idx["versions"][0]["generated_at"] == "T2"  # 置き換え


def test_update_index_keeps_feed_info():
    idx = versioning.update_index(
        None, pair="p", version="2026.7.11.1", generated_at="T1",
        feed_info={"org": "o"},
    )
    idx = versioning.update_index(
        idx, pair="p", version="2026.8.1.1", generated_at="T2")
    assert idx["feed"] == {"org": "o"}


def test_latest_version():
    assert versioning.latest_version(None) is None
    assert versioning.latest_version({"versions": []}) is None
    idx = versioning.update_index(
        None, pair="p", version="2026.7.11.1", generated_at="T1")
    assert versioning.latest_version(idx) == "2026.7.11.1"
