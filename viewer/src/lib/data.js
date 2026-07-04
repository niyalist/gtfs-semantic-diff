// バンドルの索引化 (App から各コンポーネントへ渡す派生データ)

const STOP_TYPES = new Set([
  "STOP_ADDED", "STOP_REMOVED", "STOP_RENAMED", "STOP_RELOCATED",
  "PLATFORM_ADDED", "PLATFORM_REMOVED", "PLATFORM_CHANGED", "ACCESSIBILITY_CHANGED",
]);
const VALIDATION_TYPES = new Set([
  "TECHNICAL_ID_CHURN", "UNEXPLAINED_RESIDUAL", "FEED_VALIDITY_CHANGED",
]);

export function buildIndex(bundle) {
  const events = bundle.events.events;
  const context = bundle.events.context || {};

  const rawdiffById = new Map(bundle.rawdiffs.map((d) => [d.rawdiff_id, d]));

  const routeEvents = events.filter(
    (e) => e.subject?.route_family && !STOP_TYPES.has(e.type) && !VALIDATION_TYPES.has(e.type)
  );
  const stopEvents = events.filter((e) => STOP_TYPES.has(e.type));
  const validationEvents = events.filter((e) => VALIDATION_TYPES.has(e.type));
  const feedEvents = events.filter(
    (e) =>
      !routeEvents.includes(e) && !stopEvents.includes(e) && !validationEvents.includes(e)
  );

  const byGroup = new Map();
  for (const e of routeEvents) {
    const g = e.subject.route_group || e.subject.route_family;
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push(e);
  }

  const groupInfo = new Map((context.route_groups || []).map((g) => [g.name, g]));
  const familyStructure = new Map(
    (context.family_structure || []).map((s) => [s.route_family, s])
  );
  const profilesByFamily = new Map();
  for (const p of context.band_profiles || []) {
    if (!profilesByFamily.has(p.route_family)) profilesByFamily.set(p.route_family, []);
    profilesByFamily.get(p.route_family).push(p);
  }

  const timetableByKey = new Map(
    (bundle.timetables || []).map((tt) => [
      `${tt.route_family}|${tt.direction}|${tt.day_type}`,
      tt,
    ])
  );

  const unchangedGroups = (context.route_groups || []).filter(
    (g) => !byGroup.has(g.name)
  );

  // 章順: major を含む group を先に
  const groupOrder = [...byGroup.keys()].sort((a, b) => {
    const am = byGroup.get(a).some((e) => e.severity === "major") ? 0 : 1;
    const bm = byGroup.get(b).some((e) => e.severity === "major") ? 0 : 1;
    return am - bm || a.localeCompare(b, "ja");
  });

  return {
    events, context,
    rawdiffById,
    routeEvents, stopEvents, validationEvents, feedEvents,
    byGroup, groupOrder, groupInfo, familyStructure, profilesByFamily,
    timetableByKey, unchangedGroups,
    lowCohesion:
      bundle.events.config_snapshot?.identity?.route_group?.low_cohesion_note ?? 0.2,
    accounting: bundle.events.accounting,
    feed: bundle.events.feed,
    geometry: bundle.geometry,
    catalog: bundle.catalog,
    meta: bundle.meta,
  };
}

export function timetableFor(index, e) {
  const s = e.subject || {};
  if (!s.route_family || s.day_type == null) return null;
  return (
    index.timetableByKey.get(`${s.route_family}|${s.direction ?? ""}|${s.day_type}`) || null
  );
}

export function mapTargets(index, e) {
  // イベントに応じて地図でハイライトする対象を決める
  const s = e.subject || {};
  if (STOP_TYPES.has(e.type) && s.stop_cluster) {
    return { baseNames: [s.stop_cluster], shapeIds: [] };
  }
  const q = e.quantification || {};
  const shapeIds = [];
  if (s.shape_id) shapeIds.push(s.shape_id);
  if (q.old_shape) shapeIds.push(q.old_shape);
  if (q.new_shape) shapeIds.push(q.new_shape);
  if (shapeIds.length) return { baseNames: [], shapeIds: [...new Set(shapeIds)] };
  // パターン変化: 追加/削除された停留所を示す
  if (q.stops?.length) return { baseNames: q.stops, shapeIds: [] };
  return null;
}
