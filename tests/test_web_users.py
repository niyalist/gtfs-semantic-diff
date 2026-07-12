"""infra/runtime/webusers.py (W3-2b ログインユーザー純ロジック) の単体テスト。"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "webusers",
    Path(__file__).resolve().parent.parent / "infra" / "runtime" / "webusers.py",
)
webusers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(webusers)


def test_user_id_is_deterministic_and_email_normalized():
    a = webusers.user_id_from_email("Niya@Example.com ")
    b = webusers.user_id_from_email("niya@example.com")
    assert a == b  # 大文字小文字・空白の揺れは同一人物
    assert a.startswith("u") and len(a) == 24
    assert a != webusers.user_id_from_email("other@example.com")


def test_user_id_rejects_garbage():
    with pytest.raises(ValueError):
        webusers.user_id_from_email("")
    with pytest.raises(ValueError):
        webusers.user_id_from_email("not-an-email")


def test_history_sk_sorts_by_time():
    older = webusers.history_sk("2026-07-10T01:00:00+00:00", "job-a")
    newer = webusers.history_sk("2026-07-11T01:00:00+00:00", "job-b")
    assert newer > older  # ISO 8601 の辞書順 = 時刻順 (sk 降順で新しい順に読める)


def test_zip_keys():
    assert webusers.zip_sk("abc123") == "zip#abc123"
    assert webusers.zip_s3_key("u0123", "abc123") == "userzips/u0123/abc123.zip"


def test_zip_display_name():
    name = webusers.zip_display_name(
        "永井バス", "2025-10-01", "2026-07-11T05:00:00+00:00")
    assert name == "永井バス 2025-10-01〜 (アップロード 2026-07-11)"


def test_zip_display_name_fallbacks():
    # agency 欠損 → fallback (feed_publisher_name / ファイル名)
    name = webusers.zip_display_name("", "", "2026-07-11", fallback="old.zip")
    assert name == "old.zip (アップロード 2026-07-11)"
    assert webusers.zip_display_name("", "", "") == "GTFS"


def test_is_admin_allowlist():
    assert webusers.is_admin("Niya2828@Gmail.com ", "niya2828@gmail.com")
    assert webusers.is_admin("a@x.jp", "b@y.jp, a@x.jp")
    assert not webusers.is_admin("other@x.jp", "a@x.jp")
    assert not webusers.is_admin("", "a@x.jp")
    assert not webusers.is_admin("a@x.jp", "")
