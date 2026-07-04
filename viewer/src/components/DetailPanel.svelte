<script>
  import { t } from "../lib/i18n.js";
  import { timetableFor, mapTargets } from "../lib/data.js";
  import EvidenceTable from "./EvidenceTable.svelte";
  import TimetableView from "./TimetableView.svelte";
  import MapView from "./MapView.svelte";
  import PatternDiff from "./PatternDiff.svelte";

  export let index;
  export let event;

  $: tt = $t;
  $: timetable = timetableFor(index, event);
  $: targets = mapTargets(index, event);
  $: hasPattern = event.old_ref?.pattern && event.new_ref?.pattern;
  $: quant = Object.entries(event.quantification || {}).filter(
    ([k]) => k !== "segments"
  );
  $: segments = event.quantification?.segments || [];
</script>

{#if quant.length || event.confidence < 1}
  <h4>{tt("quantification")}</h4>
  <dl class="kv">
    {#each quant as [k, v]}
      <dt>{k}</dt>
      <dd>{typeof v === "object" ? JSON.stringify(v) : v}</dd>
    {/each}
    {#if event.confidence < 1}
      <dt>confidence</dt>
      <dd>{event.confidence}</dd>
    {/if}
  </dl>
{/if}

{#if segments.length}
  <div class="scroll-x">
    <table>
      <thead>
        <tr>
          <th>segment</th>
          <th class="num">old median</th><th class="num">new median</th>
          <th class="num">old p90</th><th class="num">new p90</th>
        </tr>
      </thead>
      <tbody>
        {#each segments as s}
          <tr>
            <td>{s.segment}</td>
            <td class="num">{s.old_median_sec}s</td><td class="num">{s.new_median_sec}s</td>
            <td class="num">{s.old_p90}s</td><td class="num">{s.new_p90}s</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

{#if hasPattern}
  <h4>{tt("pattern_change")}</h4>
  <PatternDiff oldPattern={event.old_ref.pattern} newPattern={event.new_ref.pattern} />
{/if}

{#if timetable}
  <h4>{tt("timetable")}</h4>
  <TimetableView {timetable} />
{/if}

{#if targets}
  <h4>{tt("map")}</h4>
  <MapView geometry={index.geometry} baseNames={targets.baseNames} shapeIds={targets.shapeIds} />
{/if}

<h4>{tt("evidence")} ({event.evidence.length})</h4>
<EvidenceTable {index} ids={event.evidence} />
