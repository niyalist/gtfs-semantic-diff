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
  function changeText(c) {
    const names = {
      PATTERN_EXTENDED: "延伸", PATTERN_TRUNCATED: "短縮",
      STOP_INSERTED_IN_PATTERN: "経由地追加", DETOUR_ADDED: "経由地追加",
      STOP_REMOVED_FROM_PATTERN: "経由地削除", DETOUR_REMOVED: "経由地削除",
    };
    return `${names[c.type] ?? c.type}: ${(c.stops || []).join("、")}`;
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
      {#each s.level3.filter((u) => u.absorbed_into_level2 && u.system_id === item.system_id) as u}
        <div class="sub">{#each u.changes as c}{changeText(c)} {/each}</div>
      {/each}
    </div>
  {/each}

  {#each lev3visible as u}
    <details class="lev lev3">
      <summary>
        ○ <strong>{tt("via_change")}</strong>: {u.system_label || u.family} —
        {#each u.changes as c, i}{i > 0 ? " / " : ""}{changeText(c)}{/each}
        <span class="meta">
          ({u.full_coverage ? tt("all_trips") : tt("coverage_of", u.affected_trips, u.system_trips)})
        </span>
      </summary>
      <div class="sub">
        <PatternDiff oldPattern={u.old_pattern} newPattern={u.new_pattern} />
      </div>
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
