// イベント1件の一行要約 (report/markdown.py の _event_line と対応。数値は言語中立)

export function dayLabel(dayType, tt) {
  return tt(dayType) === dayType ? dayType : tt(dayType);
}

export function subjectLabel(e, tt) {
  const s = e.subject || {};
  const parts = [];
  if (s.route_family) {
    parts.push(s.route_family);
    if (s.day_type) parts.push(dayLabel(s.day_type, tt));
  } else if (s.stop_cluster) parts.push(s.stop_cluster);
  else if (s.file) parts.push(s.file);
  else if (s.shape_id) parts.push(`shape ${s.shape_id}`);
  else if (s.files) parts.push(s.files.join(", "));
  else if (s.scope) parts.push(String(s.scope));
  return parts.join(" ");
}

export function eventLine(e, lang) {
  const q = e.quantification || {};
  const ja = lang !== "en";
  switch (e.type) {
    case "SERVICE_REDUCED":
    case "SERVICE_INCREASED":
      return `${q.time_band ?? ""} ${ja ? "帯" : ""} ${q.old_count ?? "?"}${ja ? "本" : ""} → ${q.new_count ?? "?"}${ja ? "本" : " trips"}`;
    case "TIMETABLE_SHIFTED":
      if (q.uniform)
        return ja
          ? `${q.trip_count ?? "?"}便を一様に ${q.shift_min ?? "?"} 分シフト`
          : `${q.trip_count ?? "?"} trips shifted by ${q.shift_min ?? "?"} min`;
      return ja
        ? `${q.time_band ?? ""} 帯で ${q.trips_changed ?? "?"}便の時刻変更`
        : `${q.trips_changed ?? "?"} trips re-timed in ${q.time_band ?? ""}`;
    case "FIRST_LAST_CHANGED": {
      const parts = [];
      if (Math.abs(q.first_shift_min ?? 0) >= 1)
        parts.push(`${ja ? "始発" : "first"} ${q.old_first} → ${q.new_first}`);
      if (Math.abs(q.last_shift_min ?? 0) >= 1)
        parts.push(`${ja ? "終発" : "last"} ${q.old_last} → ${q.new_last}`);
      return parts.join(ja ? "、" : ", ");
    }
    case "PATTERN_EXTENDED":
    case "PATTERN_TRUNCATED":
    case "STOP_INSERTED_IN_PATTERN":
    case "STOP_REMOVED_FROM_PATTERN":
    case "DETOUR_ADDED":
    case "DETOUR_REMOVED":
      return `${(q.stops || []).join("、")} (${q.trip_count ?? "?"}${ja ? "便" : " trips"})`;
    case "ROUTE_ADDED":
    case "ROUTE_DISCONTINUED":
    case "SEASONAL_SERVICE_CHANGED":
      return `${q.trip_count ?? "?"}${ja ? "便" : " trips"}`;
    case "ROUTE_RENAMED":
    case "STOP_RENAMED":
      return e.old_ref?.name ? `${e.old_ref.name} → ${e.new_ref?.name ?? "?"}` : "";
    case "STOP_ADDED":
    case "STOP_REMOVED":
      return ja ? `乗り場 ${q.platform_count ?? "?"} 箇所` : `${q.platform_count ?? "?"} platform(s)`;
    case "STOP_RELOCATED":
      return `${q.moved_m ?? "?"} m`;
    case "PLATFORM_CHANGED":
      if (q.stop_time_rows != null)
        return ja ? `停車 ${q.stop_time_rows} 便分の乗り場付け替え` : `${q.stop_time_rows} stop-times reassigned`;
      return `${q.moved_m ?? "?"} m`;
    case "PLATFORM_ADDED":
    case "PLATFORM_REMOVED":
      return (q.platform_ids || []).join("、");
    case "TECHNICAL_ID_CHURN":
      if (q.trip_pairs != null)
        return ja ? `trip_id 張り替え ${q.trip_pairs} 組 (ダイヤ同一)` : `${q.trip_pairs} trip_id pairs (identical schedule)`;
      if (q.old_shape) return `shape ${q.old_shape} → ${q.new_shape}`;
      return `${(q.removed_route_ids || []).join(",")} → ${(q.added_route_ids || []).join(",")}`;
    case "SHAPE_CHANGED": {
      const sig = q.significant ? (ja ? "実変形" : "significant") : (ja ? "点列変更のみ" : "resampled");
      return q.frechet_m != null ? `Fréchet ${q.frechet_m} m (${sig})` : sig;
    }
    case "FARE_CHANGED": {
      const changes = (q.price_changes || []).map((p) => `${p.fare_id}: ${p.old_price}→${p.new_price}`);
      const removed = (q.removed_fares || []).map((f) => `-${f.fare_id}(${f.price})`);
      const added = (q.added_fares || []).map((f) => `+${f.fare_id}(${f.price})`);
      return [...changes, ...removed, ...added].slice(0, 4).join(", ") || (ja ? "運賃データ変更" : "fare data changed");
    }
    case "TRAVEL_TIME_CHANGED":
      return ja ? `${q.trip_count ?? "?"}便の所要時間・時刻修正` : `${q.trip_count ?? "?"} trips re-timed`;
    case "HEADSIGN_CHANGED":
      return (q.samples || []).slice(0, 2).join(" / ");
    case "DAYTYPE_RESTRUCTURED":
      return `${(e.old_ref?.day_types || []).join("・")} → ${(e.new_ref?.day_types || []).join("・")}`;
    case "HOLIDAY_EXCEPTION_CHANGED":
      return Object.entries(q)
        .filter(([k, v]) => typeof v === "number")
        .map(([k, v]) => `${k} ${v}`)
        .join(" / ");
    case "FEED_VALIDITY_CHANGED": {
      const changed = q.changed_fields || {};
      const items = Object.entries(changed).map(([k, v]) => `${k}: ${v}`);
      return items.join("; ") || `${e.evidence_total ?? e.evidence?.length ?? 0}`;
    }
    case "UNEXPLAINED_RESIDUAL":
      return `${e.subject?.file ?? ""}: ${q.rawdiff_count ?? e.evidence_total ?? e.evidence?.length ?? 0}`;
    default: {
      const items = Object.entries(q).slice(0, 3).map(([k, v]) => `${k}=${JSON.stringify(v)}`);
      return items.join("; ");
    }
  }
}

export function fmtTime(hms) {
  if (!hms) return "";
  const [h, m] = hms.split(":");
  return `${parseInt(h, 10)}:${m}`;
}

// PI-1/PI-2 (ui_quality.md S2): 便数の「旧→新▲▼」表記の一元実装。
// タブ・折りたたみヘッダ・第1部の便数表・④件数はすべてこれを使う。
// mixed (混成世界) の側は必ず「のべ」を冠し、1日あたりと断定しない。
// 記号▲▼+数値が第1チャネル (色弱原則)
export function countText(tt, d) {
  const mo = Boolean(d.mixed_old);
  const mn = Boolean(d.mixed_new);
  const one = (n, mixed) => (mixed ? tt("gross_trips", n) : `${n}${tt("trips_count")}`);
  if (d.old === d.new && !mo && !mn) return one(d.new, false);
  if (d.old === d.new) return one(d.new, mo || mn);
  const sym = d.new > d.old ? "▲" : "▼";
  if (!mo && !mn) return `${d.old}→${d.new}${tt("trips_count")}${sym}`;
  return `${one(d.old, mo)}→${one(d.new, mn)}${sym}`;
}

// PI-3 (ui_quality.md S2): 日付ラン表示の一元実装。runs はサーバー側
// date_runs_year_split の出力 ([[a,b],…] — 年境のみ分割済み)。
// total を渡すと「(全N日)」を付ける
export function runsText(runs, more, total, lang) {
  const md = (s) => `${+s.slice(4, 6)}/${+s.slice(6, 8)}`;
  const dash = lang === "en" ? "–" : "〜";
  let out = (runs ?? [])
    .map(([a, b]) => (a === b ? md(a) : `${md(a)}${dash}${md(b)}`))
    .join(lang === "en" ? ", " : "、");
  if (more) out += lang === "en" ? ` +${more}` : ` ほか${more}区間`;
  if (total != null) out += ` (${lang === "en" ? `${total} days` : `全${total}日`})`;
  return out;
}
