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
</script>

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

  {#each lev3visible as u}
    <details class="lev lev3">
      <summary>
        ○ <strong>{tt("via_change")}</strong>: {unitText(u)}
        <span class="meta">
          ({u.systems.map((sy) => legJa(sy.leg) || sy.label).filter((v, i, a) => a.indexOf(v) === i).join("・")},
          {u.full_coverage ? tt("all_trips") : tt("coverage_of", u.affected_trips, u.system_trips)})
        </span>
      </summary>
      {#each u.systems as sy}
        <div class="sub">
          <div class="meta">{sy.label} ({legJa(sy.leg)}, {sy.affected_trips}/{sy.system_trips}{tt("trips_count")})</div>
          <PatternDiff oldPattern={sy.old_pattern} newPattern={sy.new_pattern} />
        </div>
      {/each}
    </details>
  {/each}

  {#each s.level4 as x}
    <p class="lev lev4">
      {x.net > 0 ? "▲" : x.net < 0 ? "▼" : "◇"}
      <strong>{x.label}</strong> {dayJa(x.day_type)}: {lev4text(x)}
    </p>
  {/each}

  {#if s.level5.retimed_trips || s.level5.notes.length}
    <p class="lev lev5 meta">
      ・{#if s.level5.retimed_trips}{tt("retimed_note", s.level5.retimed_trips)}{/if}
      {#each s.level5.notes as n}
        {" / "}{n.kind === "shape_changed" ? tt("shape_note", n.count) : tt("headsign_note", n.count)}
      {/each}
    </p>
  {/if}

  {#if !s.level2.length && !lev3visible.length && !s.level4.length && !s.level5.retimed_trips && !s.level5.notes.length}
    <p class="meta">{tt("no_route_changes")}</p>
  {/if}
{/if}

<style>
  .lev { margin: 0.3rem 0; }
  .lev1 { font-size: 1.05rem; }
  .lev3 summary { cursor: pointer; }
  .sub { margin: 0.3rem 0 0.3rem 1.4rem; }
  .lev5 { margin-top: 0.5rem; }
</style>
