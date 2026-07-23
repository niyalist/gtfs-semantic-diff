import { writable, derived } from "svelte/store";

// JSON (バンドル) は言語中立。言語はこのラベル層だけで切り替える (docs/design/web.md)。
export const lang = writable("ja");

const DICT = {
  ja: {
    title: "ダイヤ改正 意味的差分レポート",
    old_gen: "旧世代", new_gen: "新世代", generated: "生成日時",
    summary: "1. 全体サマリ", routes: "2. 路線別詳細", stops: "3. 停留所の変更",
    validation: "4. データ検証", unchanged_routes: "変更のない路線",
    unchanged_note: "以下の路線では路線・運行パターン・便数時刻の変化は検出されていない。",
    major_changes: "主要変更 (major)", event: "イベント", count: "件数",
    type: "種別", target: "対象", description: "内容",
    route: "路線", families: "構成系統", trips: "便数", cohesion: "凝集度",
    branch_note: "枝線構造: 系統ごとに経路が大きく異なる",
    structure: "運行系統の構成 (停車地がほぼ重ならない系統が同居)",
    band_table: "時間帯別本数 (旧→新)", direction: "方向", day: "曜日", total: "計",
    outbound: "往路", inbound: "復路",
    weekday: "平日", saturday: "土曜", sunday_holiday: "日祝", weekend: "土日",
    daily: "毎日", irregular: "特定日", inactive: "運行日なし",
    day_added_to: (base) => ` (${base}に追加)`,
    fo_special_title: "特定日・運行日なしの内訳",
    fo_special_dates: (n, a, b) => `${n}日間 (${a}〜${b})`,
    fo_special_rundates: (list, n, extra) =>
      `運行日: ${list}${extra ? ` ほか${extra}` : ""}${n > 1 ? ` (計${n}日)` : ""}`,
    fo_special_replaces: "期間中は通常ダイヤ運休 (置き換え)",
    fo_special_extra: "通常ダイヤに追加",
    fo_special_inactive: "運行日の定義なし (休止中の枠)",
    fo_scope_title: "同梱世代と比較範囲",
    fo_scope_window: (a, b) => `比較対象期間: ${a}〜${b} (両世代の共通有効期間)`,
    fo_scope_primary: (p) => `比較したダイヤ期間: ${p}`,
    fo_scope_identical: (p) => `運行内容が同一の期間 (変化なし): ${p}`,
    fo_scope_excluded_old: (s, t) =>
      `旧側の比較対象外: ${s} service・${t}便 (期限切れ・持ち越し世代)`,
    fo_scope_excluded_new: (s, t) =>
      `新側の比較対象外: ${s} service・${t}便 (期限切れ・持ち越し世代)`,
    cal_title: "運行日カレンダー",
    cal_legend: "平/土/休/週/毎/曜 = その日に走るダイヤ区分・▲ = 曜日と異なるダイヤで運行 (祝日等の振替)・◆ = 特定日運行あり・「・」 = 運行なし。期間 (世代・季節) の切れ目は太罫線と背景で示す",
    cal_periods: (p) => `期間: ${p}`,
    cal_swap: "曜日と異なるダイヤ (振替)",
    cal_special: "特定日運行あり",
    evidence: "根拠データ (RawDiff)", quantification: "数値詳細",
    timetable: "発車時刻表 (始発停留所基準)", map: "地図",
    pattern_change: "停車パターン変化", old: "旧", new: "新",
    file: "ファイル", kind: "種別", key: "キー", column: "カラム",
    old_value: "旧値", new_value: "新値",
    more_rows: (n) => `…ほか ${n} 件`,
    explained_ratio: "説明被覆率 (explained_ratio)",
    residual_all: "未説明の残差 (全件)", no_residual: "未説明の残差はない (全 RawDiff が説明済み)。",
    stops_count: "停", trips_count: "便",
    close: "閉じる", open_detail: "詳細 ▸", close_detail: "詳細 ▾",
    no_data: "データがありません。gtfs-semantic-diff compare --html で生成された HTML を開いてください。",
    id_churn: "ID 張り替え (意味変化なし)",
    added_stop: "新設", removed_stop: "廃止", matched_stop: "継続",
    attribution_note: "地図: 国土地理院タイル",
    mode_normal: "レポート", mode_verify: "検証モード",
    overview: "路線概要", systems: "運行系統", summary_changes: "変化のサマリー",
    lev1_added: "この路線は新設された", lev1_removed: "この路線は廃止された",
    system_added: "系統の新設", system_removed: "系統の廃止",
    via_change: "経由の変更", all_trips: "全便",
    stops_added: "追加", stops_removed: "削除",
    affected: "対象", coverage_of: (a, b) => `${b}便中${a}便`,
    net_inc: (n) => `純増${n}便`, net_dec: (n) => `純減${n}便`, net_zero: "増減なし",
    inc_dec: (i, d) => `増${i}・減${d}`,
    shape_note: (n) => `経路形状の変更 ${n}件`,
    headsign_note: (n) => `行先表示の変更 ${n}箇所`,
    // R19: 便ラベル (代表1ラベル) とその集約表示
    trip_labels: {
      added: "新規", removed: "廃止", rerouted: "経由変更",
      shortened: "区間短縮", extended: "区間延長",
      retimed: "時刻変更", retimed_minor: "微調整", unchanged: "変更なし",
    },
    chip_new: "新設", chip_removed: "廃止", chip_systems: "系統再編",
    chip_reroute: "経由変更", chip_retime: "ダイヤ変更", chip_minor: "微調整",
    digest_label: "一言で",
    dg_route_added: (n) => `路線の新設 (${n}便)`,
    dg_route_removed: (n) => `路線の廃止 (${n}便)`,
    dg_systems: (a, r) =>
      [a ? `系統の新設${a}` : "", r ? `系統の廃止${r}` : ""].filter(Boolean).join("・"),
    dg_reroute: (n) => `経由変更${n}便`,
    dg_trips_day: (day, o, n) =>
      n > o ? `${day}${n - o}便増` : `${day}${o - n}便減`,
    dg_retime: (n, m) => `${m}分超の時刻変更${n}便`,
    dg_retime_minor: (n) => `ダイヤ微調整${n}便`,
    dg_notes_only: (s, h) =>
      "便・便数の変化なし ("
      + [s ? `経路形状${s}件` : "", h ? `行先表示${h}箇所` : ""].filter(Boolean).join("・")
      + "のみ)",
    dg_sep: "、", dg_end: "。",
    via_scale: (ns, nt) => `${ns}系統・${nt}便`,
    retimed_major_note: (n, m) => `${m}分超の時刻変更 ${n}便`,
    retimed_minor_note: (n) => `時刻の微調整 ${n}便`,
    former_names: "旧名称",
    similar_candidates: "内容が類似する路線 (対応の可能性)",
    similar_one: (name, sim) => `${name} (類似度${sim})`,
    mode_old: "旧", mode_new: "新", mode_diff: "差分",
    col_added: "新", col_removed: "廃",
    show_map: "地図を表示 (系統別)", legend: "凡例",
    expand_all: "すべて展開", collapse_all: "すべて折りたたむ",
    trips_label: "便数", timetables: "時刻表 (新旧比較)",
    changed_cols: (n) => `変更 ${n}列`, no_route_changes: "この路線に変化はない",
    verify_hint: "イベント一覧・根拠データ (RawDiff)・路線に紐付かない変化 (運賃等) は検証モードで表示",
    diff_legend: "差分表示: 太字+旧時刻併記=時刻変更 / 取り消し線+廃=廃止便 / 下線+新=新設便",
    stop_changes: "停留所の変化",
    sc_renamed: "改称", sc_relocated: "移設", sc_added: "新設", sc_removed: "廃止",
    sc_platform: "乗り場の変更 (詳細)",
    sc_no_group: "(路線に属さない)",
    sc_affected_routes: "関係路線",
    sc_moved: (m) => `約${Math.round(m)}m 移動`,
    sc_map_legend: "地図: 【改】改称 / 【移】移設 (旧位置から破線) / 【新】新設 / 【廃】廃止",
    sc_platform_kinds: { PLATFORM_CHANGED: "乗り場変更", PLATFORM_ADDED: "乗り場新設", PLATFORM_REMOVED: "乗り場廃止" },
    part1_title: "1. フィード全体の変化",
    part2_title: "2. 停留所の変化",
    part3_title: "3. 路線毎の変化",
    part4_title: "4. その他の変化",
    fo_files: "ファイル対応表",
    fo_file: "ファイル", fo_rows: "行数 (旧→新)",
    fo_added: "追加", fo_removed: "削除", fo_changed: "変更",
    fo_status_added: "【新規】", fo_status_removed: "【削除】",
    fo_period: "サービス期間",
    fo_day_types: "曜日区分ごとの便数 (旧→新)",
    fo_meta_events: "フィード級の変化 (期間・事業者・カレンダー・運賃等)",
    fo_no_meta: "フィード級の変化はない。",
    sc_none: "停留所の変化はない。",
    part4_note: "第1〜3部で個別に説明していない変化の件数。内容は検証モードで確認できる。",
    part4_none: "第1〜3部で説明されない変化はない。",
    count_unit: (n) => `${n} 件`,
    fo_ev_changes: (n) => `変更 ${n}件`,
    fo_ev_rows: (n) => `${n}行`,
    fo_hx_window: (a, b) => `新旧共通期間 (${a}〜${b}) 内の実質的な変更`,
    fo_hx_mechanical: (n) => `期間ずれによる機械的な差 ${n}件`,
    fo_hx_none: "実質的な変更なし",
    fo_fare_price: (n) => `運賃額の変更 ${n}件`,
    fo_fare_removed: (n) => `廃止された運賃区分 ${n}件`,
    fo_fare_added: (n) => `新設された運賃区分 ${n}件`,
    fo_fare_rules: (n) => `適用区間 (fare_rules) の差分 ${n}行`,
    fo_yen: (o, n) => `${o}円→${n}円`,
    fo_daytypes_arrow: " → ",
    cov_title: "網羅性 (説明台帳)",
    src_line: "出典",
    src_license: "ライセンス",
    fb_report: "この結果について問題を報告",
    fb_hint: "検出漏れ・誤分類・表示の不具合などをお知らせください。報告にはこのレポートの版固定 URL が添付されます。",
    fb_placeholder: "例: ○○線の廃止が検出されていない、便数の集計が時刻表と合わない、など",
    fb_event_id: "関連するイベント ID (任意)",
    fb_send: "送信",
    fb_thanks: "報告を受け付けました。ありがとうございます。",
    ver_generated: "このレポートの生成版",
    ver_newer: "より新しい解析版があります",
    ver_other: "版を選択",
    ver_latest: "(最新)",
    cov_rawdiff: "RawDiff 被覆 (explained_ratio)",
    cov_report: "レポート被覆率 (イベント→第1〜3部)",
    cov_lev1: "新設/廃止扱いの便数比率 (lev1_trip_ratio)",
    cov_lev1_note: "路線の改称・再編を取りこぼすとこの値が跳ねる (対応付け品質の監視用)",
    cov_events_unit: "イベント",
    cov_type_counts: "イベント種類別件数",
    dest_title: "イベント一覧 (表示先別)",
    dest4_note: "レポートでは件数のみ提示 (個別説明なし)",
    fdb_title: "ファイル別の生差分 (GTFS 形式)",
    fdb_note: "全 RawDiff をファイル・種類ごとに列挙する。各行の右端は「説明イベント → レポートの表示先」。",
    fdb_residual_only: "未説明 (UNEXPLAINED_RESIDUAL) のみ表示",
    fdb_explained_by: "説明イベント → 表示先",
    fdb_unexplained: "未説明",
    fdb_columns: "列変更",
    kind_file_added: "ファイル追加", kind_file_removed: "ファイル削除",
    kind_column_added: "列追加", kind_column_removed: "列削除",
    kind_row_added: "行追加", kind_row_removed: "行削除",
    kind_field_changed: "値変更",
    kind_rows_removed_bulk: "行削除 (集約: 値=行数)",
    kind_rows_added_bulk: "行追加 (集約: 値=行数)",
    kind_rows_changed_bulk: "行変更 (集約: 値=行数)",
  },
  en: {
    title: "GTFS semantic diff report",
    old_gen: "Old", new_gen: "New", generated: "Generated",
    summary: "1. Summary", routes: "2. Routes", stops: "3. Stop changes",
    validation: "4. Data validation", unchanged_routes: "Unchanged routes",
    unchanged_note: "No route, pattern, or service-level changes were detected on these routes.",
    major_changes: "Major changes", event: "Event", count: "Count",
    type: "Type", target: "Target", description: "Description",
    route: "Route", families: "Sub-routes", trips: "Trips", cohesion: "Cohesion",
    branch_note: "Branch structure: sub-routes serve mostly different corridors",
    structure: "Service branches (mostly disjoint stop sequences)",
    band_table: "Trips per time band (old→new)", direction: "Dir", day: "Days", total: "Total",
    outbound: "Outbound", inbound: "Inbound",
    weekday: "Weekday", saturday: "Saturday", sunday_holiday: "Sun/Hol", weekend: "Weekend",
    daily: "Daily", irregular: "Irregular", inactive: "No service days",
    day_added_to: (base) => ` (extra on ${base})`,
    fo_special_title: "Irregular / inactive services",
    fo_special_dates: (n, a, b) => `${n} day(s) (${a}–${b})`,
    fo_special_rundates: (list, n, extra) =>
      `runs on ${list}${extra ? ` +${extra} more` : ""}${n > 1 ? ` (${n} days)` : ""}`,
    fo_special_replaces: "replaces regular timetable on those dates",
    fo_special_extra: "in addition to the regular timetable",
    fo_special_inactive: "no service days defined (dormant)",
    fo_scope_title: "Bundled generations and comparison scope",
    fo_scope_window: (a, b) => `Compared period: ${a}–${b} (overlap of both feeds)`,
    fo_scope_primary: (p) => `Compared schedule period: ${p}`,
    fo_scope_identical: (p) => `Periods with identical service (no change): ${p}`,
    fo_scope_excluded_old: (s, t) =>
      `Out of scope on the old side: ${s} service(s), ${t} trip(s) (expired / carried-over generation)`,
    fo_scope_excluded_new: (s, t) =>
      `Out of scope on the new side: ${s} service(s), ${t} trip(s) (expired / carried-over generation)`,
    cal_title: "Service calendar",
    cal_legend: "W/S/H/E/D/w = schedule type running that day (weekday/Sat/Sun-holiday/weekend/daily/day-of-week) · ▲ = runs a different schedule than the weekday suggests (holiday swap) · ◆ = special-date service runs · “·” = no service. Period (generation/season) breaks are shown by thick rules and shading",
    cal_periods: (p) => `Periods: ${p}`,
    cal_swap: "different schedule than the weekday (swap)",
    cal_special: "special-date service runs",
    evidence: "Evidence (raw diffs)", quantification: "Quantification",
    timetable: "Departures (at first stop)", map: "Map",
    pattern_change: "Stop pattern change", old: "old", new: "new",
    file: "File", kind: "Kind", key: "Key", column: "Column",
    old_value: "Old", new_value: "New",
    more_rows: (n) => `…and ${n} more`,
    explained_ratio: "Explained ratio",
    residual_all: "Unexplained residual (all)", no_residual: "No unexplained residual.",
    stops_count: "stops", trips_count: "trips",
    close: "Close", open_detail: "Details ▸", close_detail: "Details ▾",
    no_data: "No data. Open an HTML generated by gtfs-semantic-diff compare --html.",
    id_churn: "Technical ID churn",
    added_stop: "added", removed_stop: "removed", matched_stop: "kept",
    attribution_note: "Map: GSI tiles",
    mode_normal: "Report", mode_verify: "Verification",
    overview: "Route overview", systems: "Service branches", summary_changes: "Summary of changes",
    lev1_added: "This route is new", lev1_removed: "This route was discontinued",
    system_added: "Branch added", system_removed: "Branch removed",
    via_change: "Routing change", all_trips: "all trips",
    stops_added: "Added", stops_removed: "Removed",
    affected: "affected", coverage_of: (a, b) => `${a} of ${b} trips`,
    net_inc: (n) => `net +${n}`, net_dec: (n) => `net -${n}`, net_zero: "no net change",
    inc_dec: (i, d) => `+${i} / -${d}`,
    shape_note: (n) => `${n} shape change(s)`,
    headsign_note: (n) => `${n} headsign change(s)`,
    // R19: trip labels (one representative label per trip) and their rollups
    trip_labels: {
      added: "new", removed: "cut", rerouted: "re-routed",
      shortened: "shortened", extended: "extended",
      retimed: "re-timed", retimed_minor: "minor re-time", unchanged: "unchanged",
    },
    chip_new: "NEW", chip_removed: "DISCONTINUED", chip_systems: "branches",
    chip_reroute: "routing", chip_retime: "re-timed", chip_minor: "minor re-times",
    digest_label: "In short",
    dg_route_added: (n) => `new route (${n} trips)`,
    dg_route_removed: (n) => `route discontinued (${n} trips)`,
    dg_systems: (a, r) =>
      [a ? `${a} branch(es) added` : "", r ? `${r} branch(es) removed` : ""]
        .filter(Boolean).join(", "),
    dg_reroute: (n) => `${n} trip(s) re-routed`,
    dg_trips_day: (day, o, n) =>
      `${day} ${n > o ? "+" : "−"}${Math.abs(n - o)} trips`,
    dg_retime: (n, m) => `${n} trip(s) re-timed by more than ${m} min`,
    dg_retime_minor: (n) => `${n} trip(s) re-timed slightly`,
    dg_notes_only: (s, h) =>
      "no trip/service changes ("
      + [s ? `${s} shape change(s)` : "", h ? `${h} headsign change(s)` : ""]
        .filter(Boolean).join(", ")
      + " only)",
    dg_sep: "; ", dg_end: ".",
    via_scale: (ns, nt) => `${ns} branch(es), ${nt} trips`,
    retimed_major_note: (n, m) => `${n} trip(s) re-timed >${m} min`,
    retimed_minor_note: (n) => `${n} trip(s) re-timed slightly`,
    former_names: "Former name(s)",
    similar_candidates: "Similar routes (possible correspondence)",
    similar_one: (name, sim) => `${name} (similarity ${sim})`,
    mode_old: "Old", mode_new: "New", mode_diff: "Diff",
    col_added: "NEW", col_removed: "CUT",
    show_map: "Show map (by branch)", legend: "Legend",
    expand_all: "Expand all", collapse_all: "Collapse all",
    trips_label: "Trips", timetables: "Timetables (old vs new)",
    changed_cols: (n) => `${n} changed`, no_route_changes: "No changes on this route",
    verify_hint: "Event list, raw diffs, and non-route changes (fares etc.) are in Verification mode",
    diff_legend: "Diff view: bold + old time = re-timed / strikethrough + CUT = removed / underline + NEW = added",
    stop_changes: "Stop changes",
    sc_renamed: "Renamed", sc_relocated: "Relocated", sc_added: "Added", sc_removed: "Removed",
    sc_platform: "Platform changes (details)",
    sc_no_group: "(not on any route)",
    sc_affected_routes: "Routes",
    sc_moved: (m) => `moved ~${Math.round(m)}m`,
    sc_map_legend: "Map: [REN] renamed / [MOV] relocated (dashed from old position) / [NEW] added / [DEL] removed",
    sc_platform_kinds: { PLATFORM_CHANGED: "platform changed", PLATFORM_ADDED: "platform added", PLATFORM_REMOVED: "platform removed" },
    part1_title: "1. Feed-wide changes",
    part2_title: "2. Stop changes",
    part3_title: "3. Changes by route",
    part4_title: "4. Other changes",
    fo_files: "File comparison",
    fo_file: "File", fo_rows: "Rows (old→new)",
    fo_added: "Added", fo_removed: "Removed", fo_changed: "Changed",
    fo_status_added: "[NEW]", fo_status_removed: "[DELETED]",
    fo_period: "Service period",
    fo_day_types: "Trips per day type (old→new)",
    fo_meta_events: "Feed-level changes (validity, agency, calendar, fares, ...)",
    fo_no_meta: "No feed-level changes.",
    sc_none: "No stop changes.",
    part4_note: "Counts of changes not individually covered in parts 1–3. See Verification mode for details.",
    part4_none: "No changes beyond parts 1–3.",
    count_unit: (n) => `${n}`,
    fo_ev_changes: (n) => `${n} change(s)`,
    fo_ev_rows: (n) => `${n} row(s)`,
    fo_hx_window: (a, b) => `substantive changes within the shared window (${a}–${b})`,
    fo_hx_mechanical: (n) => `${n} mechanical difference(s) from the period shift`,
    fo_hx_none: "no substantive changes",
    fo_fare_price: (n) => `${n} fare price change(s)`,
    fo_fare_removed: (n) => `${n} fare class(es) removed`,
    fo_fare_added: (n) => `${n} fare class(es) added`,
    fo_fare_rules: (n) => `${n} fare_rules row(s) changed`,
    fo_yen: (o, n) => `¥${o}→¥${n}`,
    fo_daytypes_arrow: " → ",
    cov_title: "Coverage (explanation ledger)",
    src_line: "Source",
    src_license: "license",
    fb_report: "Report an issue with this result",
    fb_hint: "Missed changes, misclassification, display problems, etc. The pinned URL of this report version is attached.",
    fb_placeholder: "e.g. discontinuation of line X is not detected",
    fb_event_id: "Related event ID (optional)",
    fb_send: "Send",
    fb_thanks: "Thank you — your report has been recorded.",
    ver_generated: "Report generated with",
    ver_newer: "a newer analysis version exists",
    ver_other: "versions",
    ver_latest: "(latest)",
    cov_rawdiff: "RawDiff coverage (explained_ratio)",
    cov_report: "Report coverage (events → parts 1–3)",
    cov_lev1: "Trips on added/discontinued pages (lev1_trip_ratio)",
    cov_lev1_note: "Spikes when route renames/restructurings are missed (linking-quality monitor)",
    cov_events_unit: "events",
    cov_type_counts: "Event counts by type",
    dest_title: "Events by report destination",
    dest4_note: "shown only as counts in the report",
    fdb_title: "Raw diffs by file (GTFS format)",
    fdb_note: "Every raw diff, grouped by file and kind. The right column shows the explaining event and where it appears in the report.",
    fdb_residual_only: "Show only unexplained (UNEXPLAINED_RESIDUAL)",
    fdb_explained_by: "Explained by → destination",
    fdb_unexplained: "unexplained",
    fdb_columns: "column changes",
    kind_file_added: "File added", kind_file_removed: "File removed",
    kind_column_added: "Column added", kind_column_removed: "Column removed",
    kind_row_added: "Rows added", kind_row_removed: "Rows removed",
    kind_field_changed: "Values changed",
    kind_rows_removed_bulk: "Rows removed (aggregated; value = row count)",
    kind_rows_added_bulk: "Rows added (aggregated; value = row count)",
    kind_rows_changed_bulk: "Rows changed (aggregated; value = row count)",
  },
};

export const t = derived(lang, ($lang) => (key, ...args) => {
  const v = DICT[$lang][key] ?? DICT.ja[key] ?? key;
  return typeof v === "function" ? v(...args) : v;
});

// day_type → 表示名 (M10)。dow_XXXXXXX (月→日の7ビット) は値から生成する
const DOW_NAMES = {
  ja: ["月", "火", "水", "木", "金", "土", "日"],
  en: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
};
export function dayName(dayType, language) {
  if (typeof dayType === "string" && dayType.startsWith("dow_")) {
    const names = DOW_NAMES[language] ?? DOW_NAMES.ja;
    const days = [...dayType.slice(4)]
      .map((b, i) => (b === "1" ? names[i] : null))
      .filter(Boolean);
    return language === "en" ? days.join("/") : `${days.join("・")}曜`;
  }
  const v = DICT[language]?.[dayType] ?? DICT.ja[dayType];
  return typeof v === "string" ? v : dayType;
}

export function eventName(catalog, type, language) {
  const entry = catalog?.[type];
  if (!entry) return type;
  return language === "en" ? entry.en : entry.ja;
}

// SD3: YYYYMMDD 昇順リストを連続日のラン (7/21、8/11〜8/16) に畳んで表示する。
// maxRuns を超えた分は more (件数) で返し、呼び出し側が「ほか N」を付ける
export function formatDateRuns(dates, language, maxRuns = 8) {
  const toTime = (s) =>
    new Date(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)).getTime();
  const runs = [];
  let start = null;
  let prev = null;
  for (const s of dates ?? []) {
    if (prev !== null && toTime(s) - toTime(prev) === 86400000) {
      prev = s;
      continue;
    }
    if (start !== null) runs.push([start, prev]);
    start = prev = s;
  }
  if (start !== null) runs.push([start, prev]);
  const md = (s) => `${+s.slice(4, 6)}/${+s.slice(6, 8)}`;
  const dash = language === "en" ? "–" : "〜";
  const sep = language === "en" ? ", " : "、";
  const text = runs
    .slice(0, maxRuns)
    .map(([a, b]) => (a === b ? md(a) : `${md(a)}${dash}${md(b)}`))
    .join(sep);
  return { text, more: Math.max(0, runs.length - maxRuns) };
}
