<script>
  import { t } from "../lib/i18n.js";
  import { dayLabel } from "../lib/format.js";
  import EventRow from "./EventRow.svelte";

  export let index;

  $: tt = $t;

  function bandTable(families, groupEvents) {
    const changed = new Set(
      groupEvents.map(
        (e) =>
          `${e.subject.route_family}|${e.subject.direction ?? ""}|${e.subject.day_type ?? ""}`
      )
    );
    let rows = [];
    for (const f of families) {
      for (const p of index.profilesByFamily.get(f) || []) {
        rows.push(p);
      }
    }
    const filtered = rows.filter((p) =>
      changed.has(`${p.route_family}|${p.direction}|${p.day_type}`)
    );
    if (filtered.length) rows = filtered;
    const bands = [...new Set(rows.flatMap((p) => Object.keys(p.bands)))].sort();
    return { rows, bands };
  }

  function cell(p, band) {
    const [o, n] = p.bands[band] || [0, 0];
    return o !== n ? `${o}→${n}` : `${n}`;
  }
  function totals(p) {
    let o = 0, n = 0;
    for (const [a, b] of Object.values(p.bands)) { o += a; n += b; }
    return o !== n ? `${o}→${n}` : `${n}`;
  }
  function dirLabel(d) {
    return d === "0" ? tt("outbound") : d === "1" ? tt("inbound") : d || "-";
  }

  function structuresOf(families) {
    return families
      .map((f) => ({ family: f, s: index.familyStructure.get(f) }))
      .filter(({ s }) => s && s.min_cluster_jaccard < index.lowCohesion);
  }
</script>

{#each index.groupOrder as group, gi}
  {@const events = index.byGroup.get(group)}
  {@const info = index.groupInfo.get(group) || {}}
  {@const families = info.families || [...new Set(events.map((e) => e.subject.route_family))]}
  {@const multi = families.length >= 2}
  {@const bt = bandTable(families, events)}
  <details class="chapter" open={events.some((e) => e.severity === "major")}>
    <summary>
      2.{gi + 1} {group}
      <span class="count">
        {events.length} {tt("event")}{#if events.some((e) => e.severity === "major")}
          ・major{/if}
      </span>
    </summary>
    <div class="body">
      {#if multi}
        <p class="note">
          {tt("families")}: {families.join(", ")}
          {#if info.cohesion != null}
            ({tt("cohesion")} {info.cohesion.toFixed(2)}{#if info.cohesion < index.lowCohesion}
              — {tt("branch_note")}{/if})
          {/if}
        </p>
      {/if}

      {#each events as e (e.event_id)}
        <EventRow {index} event={e} showSubject={false} prefix={multi ? e.subject.route_family : ""} />
      {/each}

      {#each structuresOf(families) as { family, s }}
        <h3>{tt("structure")}{multi ? `: ${family}` : ""}</h3>
        <ul>
          {#each s.clusters as c}
            <li>
              {c.first_stop} → {c.last_stop}
              ({c.stop_count}{tt("stops_count")}・{c.trip_count}{tt("trips_count")})
            </li>
          {/each}
        </ul>
      {/each}

      {#if bt.rows.length}
        <h3>{tt("band_table")}</h3>
        <div class="scroll-x">
          <table>
            <thead>
              <tr>
                {#if multi}<th>{tt("families")}</th>{/if}
                <th>{tt("direction")}</th><th>{tt("day")}</th>
                {#each bt.bands as b}<th class="num">{b}</th>{/each}
                <th class="num">{tt("total")}</th>
              </tr>
            </thead>
            <tbody>
              {#each bt.rows as p}
                <tr>
                  {#if multi}<td>{p.route_family}</td>{/if}
                  <td>{dirLabel(p.direction)}</td>
                  <td>{dayLabel(p.day_type, tt)}</td>
                  {#each bt.bands as b}<td class="num">{cell(p, b)}</td>{/each}
                  <td class="num">{totals(p)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>
  </details>
{/each}

{#if index.unchangedGroups.length}
  <details class="chapter">
    <summary>
      2.{index.groupOrder.length + 1} {tt("unchanged_routes")}
      <span class="count">{index.unchangedGroups.length}</span>
    </summary>
    <div class="body">
      <p class="note">{tt("unchanged_note")}</p>
      <div class="scroll-x">
        <table>
          <thead>
            <tr><th>{tt("route")}</th><th>{tt("families")}</th><th class="num">{tt("trips")}</th></tr>
          </thead>
          <tbody>
            {#each [...index.unchangedGroups].sort((a, b) => a.name.localeCompare(b.name, "ja")) as g}
              {@const total = g.families.reduce((acc, f) => {
                for (const p of index.profilesByFamily.get(f) || [])
                  for (const [o, n] of Object.values(p.bands)) acc[0] += o, acc[1] += n;
                return acc;
              }, [0, 0])}
              <tr>
                <td>{g.name}</td>
                <td>{g.families.join(", ")}</td>
                <td class="num">{total[0] !== total[1] ? `${total[0]}→${total[1]}` : total[1]}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  </details>
{/if}
