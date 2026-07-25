// テスト用フィクスチャ: 実例 (しんぐう・立川) の形を最小化した page/presentation。
// 実 bundle の抜粋ではなく「同じ構造」— スキーマが変わったらここも直すこと
// (schema_version 1)

export function shinguPage() {
  // しんぐう型: 毎日①(春夏) / 毎日②(秋冬)、内容同一・運行日の変更
  return {
    route_group: "町営渡船しんぐう",
    former_names: [],
    similar_candidates: [],
    has_changes: true,
    day_totals: [
      { day_type: "daily@1", old: 6, new: 6, labels: {} },
      { day_type: "daily@2", old: 5, new: 5, labels: {} },
    ],
    day_cells: {
      "daily@1": {
        signal: "content",
        dates_old: [], dates_new: [],
        dates_old_total: 245, dates_new_total: 245,
        runs_old: [["20250301", "20251031"]], runs_old_more: 0,
        runs_new: [["20260301", "20261031"]], runs_new_more: 0,
      },
      "daily@2": {
        signal: "content",
        dates_old: [], dates_new: [],
        dates_old_total: 120, dates_new_total: 120,
        runs_old: [["20251101", "20251231"], ["20260101", "20260228"]],
        runs_old_more: 0,
        runs_new: [["20261101", "20261231"], ["20270101", "20270228"]],
        runs_new_more: 0,
      },
    },
    overview: { trip_totals: { old: 11, new: 11 }, direction_groups: [], key_stops: {} },
    summary: {
      level1: null, level2: [], level3: [], level4: [],
      level5: { retimed_major: 0, retimed_minor: 0, minor_max_min: 5, notes: [] },
    },
    digest: [],
    band_matrix: { bands: [], rows: [] },
    timetables: [],
  };
}

export function tachikawaPage() {
  // 立川型: 特定日① が混成世界 (mixed) — のべ便数+⚠+共有日
  return {
    route_group: "くるりんバス 西砂ルート",
    former_names: [],
    similar_candidates: [],
    has_changes: true,
    day_totals: [
      { day_type: "irregular@1", old: 28, new: 16, mixed_old: true, labels: {} },
    ],
    day_cells: {
      "irregular@1": {
        signal: "flow",
        mixed_old: true, mixed_new: false,
        shared_dates_old: ["20250228"], shared_dates_new: [],
        dates_old: [], dates_new: [],
        dates_old_total: 8, dates_new_total: 7,
        runs_old: [["20250228", "20250228"], ["20251229", "20251231"]],
        runs_old_more: 1,
        runs_new: [["20261229", "20261231"]], runs_new_more: 1,
      },
    },
    overview: { trip_totals: { old: 28, new: 16 }, direction_groups: [], key_stops: {} },
    summary: {
      level1: null, level2: [], level3: [], level4: [],
      level5: { retimed_major: 0, retimed_minor: 0, minor_max_min: 5, notes: [] },
    },
    digest: [],
    band_matrix: { bands: [], rows: [] },
    timetables: [],
  };
}

export function fixturePresentation() {
  return {
    feed_overview: {
      day_types: [
        { day_type: "weekday", old: 106, new: 105 },
        { day_type: "daily", old: 11, new: 11 },
        { day_type: "irregular", old: 28, new: 16, mixed_old: true },
      ],
    },
    route_pages: [shinguPage(), tachikawaPage()],
    self_check: [],
  };
}
