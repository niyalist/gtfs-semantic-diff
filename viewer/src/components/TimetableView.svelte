<script>
  import { t } from "../lib/i18n.js";
  import { fmtTime } from "../lib/format.js";

  export let timetable; // {old: [{departure,...}], new: [...]}

  $: tt = $t;

  function byHour(trips, otherSet) {
    const hours = new Map();
    for (const trip of trips) {
      const dep = trip.departure || "";
      const h = dep.split(":")[0] || "?";
      if (!hours.has(h)) hours.set(h, []);
      hours.get(h).push({
        time: fmtTime(dep).split(":")[1] ?? dep,
        full: dep,
        only: !otherSet.has(dep),
        label: `${trip.from}→${trip.to}`,
      });
    }
    return [...hours.entries()].sort((a, b) => parseInt(a[0]) - parseInt(b[0]));
  }

  $: oldSet = new Set(timetable.old.map((r) => r.departure));
  $: newSet = new Set(timetable.new.map((r) => r.departure));
  $: oldHours = byHour(timetable.old, newSet);
  $: newHours = byHour(timetable.new, oldSet);
</script>

<div class="tt">
  <div class="col">
    <h5>{tt("old")} ({timetable.old.length})</h5>
    {#each oldHours as [h, deps]}
      <div class="hour">
        <span class="h">{parseInt(h)}</span>
        <span class="mins">
          {#each deps as d}
            <span class="dep" class:only-old={d.only} title={d.label}>{d.time}</span>
          {/each}
        </span>
      </div>
    {/each}
  </div>
  <div class="col">
    <h5>{tt("new")} ({timetable.new.length})</h5>
    {#each newHours as [h, deps]}
      <div class="hour">
        <span class="h">{parseInt(h)}</span>
        <span class="mins">
          {#each deps as d}
            <span class="dep" class:only-new={d.only} title={d.label}>{d.time}</span>
          {/each}
        </span>
      </div>
    {/each}
  </div>
</div>
