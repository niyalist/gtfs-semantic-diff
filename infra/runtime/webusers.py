"""W3-2b: ログインユーザー関連の純ロジック (設計: docs/design/web.md「W3-2 詳細方針」)。

boto3 非依存 (tests/test_web_users.py で直接テストする)。

- 内部 user_id は正規化した email から決定的に導出する。Cognito の sub でなく
  email をキーにするのは、将来 IdP (メールリンク / Microsoft) を追加したとき
  同一人物のデータへ自動でリンクさせるため (w3_2_directions.md §1)。
- DynamoDB UserData テーブルは単一テーブル: pk=user_id, sk で種別を分ける。
  run#{ISO時刻}#{job_id}  — 比較履歴 (ISO 8601 は辞書順=時刻順なので sk 降順で新しい順)
  zip#{zip_id}            — 保存済みアップロード zip
"""

from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")


def normalize_email(email: str) -> str:
    """比較キー用の email 正規化。小文字化 + 前後空白除去のみ
    (Gmail のドット無視などプロバイダ固有規則は適用しない — 予測可能性優先)。"""
    return email.strip().lower()


def user_id_from_email(email: str) -> str:
    norm = normalize_email(email)
    if not norm or "@" not in norm:
        raise ValueError(f"invalid email: {email!r}")
    return "u" + hashlib.sha256(f"email:{norm}".encode()).hexdigest()[:23]


def is_admin(email: str, allowlist_csv: str) -> bool:
    """admin 許可リスト (カンマ区切り email、CDK context 由来) との照合。"""
    norm = normalize_email(email)
    allowed = {normalize_email(a) for a in allowlist_csv.split(",") if a.strip()}
    return bool(norm) and norm in allowed


def history_sk(created_at_iso: str, job_id: str) -> str:
    return f"run#{created_at_iso}#{job_id}"


def zip_sk(zip_id: str) -> str:
    return f"zip#{zip_id}"


def zip_s3_key(user_id: str, zip_id: str) -> str:
    return f"userzips/{user_id}/{zip_id}.zip"


def zip_display_name(
    agency_name: str,
    from_date: str,
    uploaded_at_iso: str,
    fallback: str = "",
) -> str:
    """保存 zip の表示名を自動生成する (決定 §6-4)。

    例: `永井バス 2025-10-01〜 (アップロード 2026-07-11)`。
    agency_name が無ければ fallback (feed_publisher_name やファイル名)。
    """
    name = _WS.sub(" ", (agency_name or fallback or "GTFS").strip())
    period = f" {from_date}〜" if from_date else ""
    uploaded = uploaded_at_iso[:10] if uploaded_at_iso else ""
    suffix = f" (アップロード {uploaded})" if uploaded else ""
    return f"{name}{period}{suffix}"
