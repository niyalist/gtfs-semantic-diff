"""イベントタイプカタログ (docs/design/ontology.md v0.2 準拠)。

英語 ID + 日本語表示名を対で管理する (CLAUDE.md 開発ルール)。
severity は既定値であり、個々の ChangeEvent は文脈に応じて上書きしてよい
(例: SERVICE_REDUCED は通勤帯なら major、それ以外は minor)。
"""

from __future__ import annotations

from dataclasses import dataclass

SEVERITY_MAJOR = "major"
SEVERITY_MINOR = "minor"
SEVERITY_INFO = "info"

SEVERITIES = frozenset({SEVERITY_MAJOR, SEVERITY_MINOR, SEVERITY_INFO})


@dataclass(frozen=True)
class EventTypeDef:
    type_id: str
    display_name_ja: str
    category: str  # A(路線)/B(パターン)/C(便数・時刻)/D(停留所)/E(カレンダー)/F(メタ・形式)
    default_severity: str


_DEFS = [
    # A. 路線・系統レベル
    ("ROUTE_ADDED", "路線新設", "A", SEVERITY_MAJOR),
    ("ROUTE_DISCONTINUED", "路線廃止", "A", SEVERITY_MAJOR),
    ("ROUTE_RENAMED", "路線名変更", "A", SEVERITY_MINOR),
    ("ROUTE_SPLIT", "路線分割", "A", SEVERITY_MAJOR),
    ("ROUTE_MERGED", "路線統合", "A", SEVERITY_MAJOR),
    ("THROUGH_SERVICE_INTRODUCED", "直通運転開始", "A", SEVERITY_MAJOR),
    ("THROUGH_SERVICE_DISCONTINUED", "直通運転終了", "A", SEVERITY_MAJOR),
    # B. 運行パターンレベル
    ("PATTERN_EXTENDED", "運行区間延長", "B", SEVERITY_MAJOR),
    ("PATTERN_TRUNCATED", "運行区間短縮", "B", SEVERITY_MAJOR),
    ("STOP_INSERTED_IN_PATTERN", "経由停留所追加", "B", SEVERITY_MINOR),
    ("STOP_REMOVED_FROM_PATTERN", "経由停留所削除", "B", SEVERITY_MINOR),
    ("DETOUR_ADDED", "経由地追加", "B", SEVERITY_MINOR),
    ("DETOUR_REMOVED", "経由地解消", "B", SEVERITY_MINOR),
    ("TIME_BAND_VARIANT", "時間帯限定経路の変更", "B", SEVERITY_MINOR),
    ("SHAPE_CHANGED", "経路形状変更", "B", SEVERITY_MINOR),
    # C. 便数・時刻レベル
    ("SERVICE_REDUCED", "減便", "C", SEVERITY_MINOR),
    ("SERVICE_INCREASED", "増便", "C", SEVERITY_MINOR),
    ("TRIPS_TRUNCATED", "一部便の区間短縮", "C", SEVERITY_MAJOR),
    ("FIRST_LAST_CHANGED", "始発・終発時刻変更", "C", SEVERITY_MAJOR),
    ("TIMETABLE_SHIFTED", "時刻一斉シフト", "C", SEVERITY_INFO),
    ("TRAVEL_TIME_CHANGED", "所要時間変更", "C", SEVERITY_MINOR),
    ("DWELL_TIME_CHANGED", "停車時分変更", "C", SEVERITY_INFO),
    # D. 停留所レベル
    ("STOP_ADDED", "停留所新設", "D", SEVERITY_MAJOR),
    ("STOP_REMOVED", "停留所廃止", "D", SEVERITY_MAJOR),
    ("STOP_RENAMED", "停留所改称", "D", SEVERITY_MINOR),
    ("STOP_RELOCATED", "停留所移設", "D", SEVERITY_MINOR),
    ("PLATFORM_CHANGED", "乗り場変更", "D", SEVERITY_MINOR),
    ("PLATFORM_ADDED", "乗り場新設", "D", SEVERITY_INFO),
    ("PLATFORM_REMOVED", "乗り場廃止", "D", SEVERITY_INFO),
    # E. 運行日・カレンダー
    ("DAYTYPE_RESTRUCTURED", "曜日ダイヤ区分再編", "E", SEVERITY_MAJOR),
    ("HOLIDAY_EXCEPTION_CHANGED", "祝日・特日運行の変更", "E", SEVERITY_INFO),
    ("SEASONAL_SERVICE_CHANGED", "期間限定運行の変更", "E", SEVERITY_MINOR),
    # F. 運用形態・メタデータ・形式層
    ("DEMAND_RESPONSIVE_CHANGE", "デマンド運行への移行兆候", "F", SEVERITY_MAJOR),
    ("FARE_CHANGED", "運賃改定", "F", SEVERITY_MAJOR),
    ("FEED_VALIDITY_CHANGED", "フィード有効期間更新", "F", SEVERITY_INFO),
    ("AGENCY_INFO_CHANGED", "事業者情報変更", "F", SEVERITY_INFO),
    ("TRANSLATION_CHANGED", "翻訳データ変更", "F", SEVERITY_INFO),
    ("ACCESSIBILITY_CHANGED", "バリアフリー情報変更", "F", SEVERITY_MINOR),
    ("TECHNICAL_ID_CHURN", "ID 張り替え(意味変化なし)", "F", SEVERITY_INFO),
    ("UNEXPLAINED_RESIDUAL", "未説明の残差", "F", SEVERITY_INFO),
]

EVENT_TYPES: dict[str, EventTypeDef] = {
    type_id: EventTypeDef(type_id, name_ja, category, severity)
    for type_id, name_ja, category, severity in _DEFS
}


def display_name_ja(type_id: str) -> str:
    return EVENT_TYPES[type_id].display_name_ja
