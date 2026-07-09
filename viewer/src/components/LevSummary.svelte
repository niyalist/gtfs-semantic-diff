<script>
  import { t } from "../lib/i18n.js";
  import PatternDiff from "./PatternDiff.svelte";

  export let page;
  $: tt = $t;
  $: s = page.summary;
  $: lev3visible = s.level3.filter((u) => !u.absorbed_into_level2);

  function dayJa(d) {
    return tt(d) === d ? d : tt(d);
  }
  function lev4text(x) {
    const net = x.net > 0 ? tt("net_inc", x.net) : x.net < 0 ? tt("net_dec", -x.net) : tt("net_zero");
    return `${net} (${tt("inc_dec", x.increased, x.decreased)})`;
  }
  function unitText(u) {
    const parts = [];
    if (u.added_stops.length) parts.push(`${tt("stops_added")}: ${u.added_stops.join("、")}`);
    if (u.removed_stops.length) parts.push(`${tt("stops_removed")}: ${u.removed_stops.join("、")}`);
    return parts.join(" / ") || tt("via_change");
  }
  function legJa(leg) {
    return leg === "reverse" ? tt("inbound") : leg === "forward" ? tt("outbound") : "";
  }
  // R19: 一言ダイジェスト。bundle の構造化事実を i18n テンプレートで文章化
  function factText(f) {
    if (f.kind === "route_added") return tt("dg_route_added", f.trips);
    if (f.kind === "route_removed") return tt("dg_route_removed", f.trips);
    if (f.kind === "systems") return tt("dg_systems", f.added, f.removed);
    if (f.kind === "reroute") return tt("dg_reroute", f.trips);
    if (f.kind === "trips")
      return f.days.map((d) => tt("dg_trips_day", dayJa(d.day_type), d.old, d.new)).join(tt("dg_sep"));
    if (f.kind === "retime") return tt("dg_retime", f.trips, f.minor_max_min);
    if (f.kind === "retime_minor") return tt("dg_retime_minor", f.trips);
    if (f.kind === "notes_only") return tt("dg_notes_only", f.shape, f.headsign);
    return "";
  }
  // Lev.1 (路線新廃) は本文1行と同内容になるためダイジェストは出さない
  $: digestText = s.level1
    ? ""
    : (page.digest ?? []).map(factText).filter(Boolean).join(tt("dg_sep"));
  $: lev5parts = [
    s.level5.retimed_major ? tt("retimed_major_note", s.level5.retimed_major, s.level5.minor_max_min) : null,
    s.level5.retimed_minor ? tt("retimed_minor_note", s.level5.retimed_minor) : null,
    ...s.level5.notes.map((n) =>
      n.kind === "shape_changed" ? tt("shape_note", n.count) : tt("headsign_note", n.count)),
  ].filter(Boolean);
</script>

{#if digestText}
  <p class="digest"><strong>{tt("digest_label")}:</strong> {digestText}{tt("dg_end")}</p>
{/if}

{#if s.level1}
  <p class="lev lev1">
    ◆ <strong>{s.level1.kind === "added" ? tt("lev1_added") : tt("lev1_removed")}</strong>
    ({s.level1.trips}{tt("trips_count")})
  </p>
{:else}
  {#each s.level2 as item}
    <div class="lev lev2">
      ◆ <strong>{item.kind === "system_added" ? tt("system_added") : tt("system_removed")}</strong>:
      {item.label} ({item.trips}{tt("trips_count")})
      {#each s.level3.filter((u) => u.absorbed_into_level2 && u.systems.some((sy) => sy.system_id === item.system_id)) as u}
        <div class="sub">{unitText(u)}</div>
      {/each}
    </div>
  {/each}

  <!-- R19: 経由の変更は「変更があった」ことと規模だけを1行で。詳細は展開時 -->
  {#each lev3visible as u}
    <details class="lev lev3">
      <summary>
        ○ <strong>{tt("via_change")}</strong>:
        {tt("via_scale", u.systems.length, u.affected_trips)}
        <span class="meta">
          ({u.full_coverage ? tt("all_trips") : tt("coverage_of", u.affected_trips, u.system_trips)})
        </span>
      </summary>
      <div class="sub">{unitText(u)}</div>
      {#each u.systems as sy}
        <div class="sub">
          <div class="meta">{sy.label} ({legJa(sy.leg)}, {sy.affected_trips}/{sy.system_trips}{tt("trips_count")})</div>
          <PatternDiff oldPattern={sy.old_pattern} newPattern={sy.new_pattern} />
        </div>
      {/each}
    </details>
  {/each}

  <!-- R19 改: 増減便は曜日単位1行 (方向・系統別の内訳は③時間帯別本数が担う) -->
  {#each s.level4 as x}
    <p class="lev lev4">
      {x.net > 0 ? "▲" : x.net < 0 ? "▼" : "◇"}
      <strong>{dayJa(x.day_type)}</strong>: {lev4text(x)}
    </p>
  {/each}

  {#if lev5parts.length}
    <p class="lev lev5 meta">・{lev5parts.join(" / ")}</p>
  {/if}

  {#if !s.level2.length && !lev3visible.length && !s.level4.length && !lev5parts.length}
    <p class="meta">{tt("no_route_changes")}</p>
  {/if}
{/if}

<style>
  .digest {
    margin: 0.3rem 0 0.6rem;
    padding: 0.4rem 0.7rem;
    background: var(--bg-soft);
    border-left: 3px solid var(--fg);
    border-radius: 3px;
  }
  .lev { margin: 0.3rem 0; }
  .lev1 { font-size: 1.05rem; }
  .lev3 summary { cursor: pointer; }
  .sub { margin: 0.3rem 0 0.3rem 1.4rem; }
  .lev5 { margin-top: 0.5rem; }
</style>
