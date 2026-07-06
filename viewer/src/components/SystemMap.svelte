<script>
  import { onMount, onDestroy } from "svelte";
  import maplibregl from "maplibre-gl";
  import "maplibre-gl/dist/maplibre-gl.css";
  import { t } from "../lib/i18n.js";

  export let systems = []; // presentation の systems (polyline: [[lat,lon],...])
  export let keyStops = {}; // 停留所名 → tier (1|2)。無指定は 3 (全停留所)
  export let highlightStops = [];

  let container;
  let map;
  $: tt = $t;

  // 原則5: 色 + 線種 (dash) の二重チャネル。凡例にも同じ組を出す
  const PALETTE = ["#0b6e4f", "#8a2be2", "#b3560f", "#0b4f6e", "#6e0b3c", "#3c6e0b"];
  const DASHES = [null, [2, 1.5], [0.5, 1.2], [3, 1, 1, 1], [1, 1], [4, 2]];

  export function styleOf(i) {
    return { color: PALETTE[i % PALETTE.length], dash: DASHES[i % DASHES.length] };
  }

  onMount(() => {
    map = new maplibregl.Map({
      container,
      style: {
        version: 8,
        // 日本語ラベル用グリフ (オンライン時のみ。タイルと同様の外部依存)
        glyphs: "https://glyphs.geolonia.com/{fontstack}/{range}.pbf",
        sources: {
          gsi: {
            type: "raster",
            tiles: ["https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "国土地理院",
          },
        },
        layers: [{ id: "gsi", type: "raster", source: "gsi" }],
      },
      attributionControl: { compact: true },
    });
    map.on("load", () => {
      let minLon = 180, minLat = 90, maxLon = -180, maxLat = -90, found = false;
      // オフセット = 「進行方向の右側レーン」方式。
      // line-offset は線の進行方向基準 (正=右) なので、全系統にページ内で一意の
      // レーン番号 (1始まり) を割り当てて右側へずらす。これで
      //  (a) 対向方向の系統は自動的に反対側へ並ぶ (起終点が完全逆転でなく
      //      別方向グループに分類された往復でも、レーンが異なるため分離)
      //  (b) 循環線が同じ道路を往復する区間は、進行方向が逆なので同一線内でも
      //      左右に分かれる (レーン0だと自分自身と重なる — これが循環線の重なりの原因)
      //  (c) 同方向で区間を共有する系統同士もレーン差で分離
      // ネットワーク全体の交錯最少化は狙わない (要件通りの簡便法)。
      const laneOf = systems.map((_, i) => i + 1);
      systems.forEach((s, i) => {
        // 連続する同一座標を除去 (乗り場が同一クラスタ座標の場合の offset 計算の乱れ防止)
        const coords = (s.polyline || [])
          .map(([lat, lon]) => [lon, lat])
          .filter((c, k, arr) => k === 0 || c[0] !== arr[k - 1][0] || c[1] !== arr[k - 1][1]);
        if (coords.length < 2) return;
        for (const [lon, lat] of coords) {
          found = true;
          minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
          minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
        }
        const { color, dash } = styleOf(i);
        const lane = laneOf[i];
        const paint = {
          "line-color": color,
          // 線幅: ズーム連動を強めに (拡大時に細すぎる問題への対応)
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            10, s.status === "removed" ? 2.5 : 3.5,
            13, s.status === "removed" ? 4 : 6,
            15, s.status === "removed" ? 6 : 9,
            17, s.status === "removed" ? 9 : 14,
          ],
          "line-offset": [
            "interpolate", ["linear"], ["zoom"],
            10, lane * 1.8, 13, lane * 4, 15, lane * 6.5, 17, lane * 10,
          ],
          "line-opacity": s.status === "removed" ? 0.6 : 0.9,
        };
        if (dash) paint["line-dasharray"] = dash;
        map.addSource(`sys${i}`, {
          type: "geojson",
          data: { type: "Feature", geometry: { type: "LineString", coordinates: coords } },
        });
        map.addLayer({ id: `sys${i}`, type: "line", source: `sys${i}`, paint });
      });

      // 停留所点 + tier 付きラベル
      const stopFeatures = [];
      const seen = new Set();
      systems.forEach((s) => {
        (s.polyline || []).forEach(([lat, lon], idx) => {
          const name = s.stops[idx] ?? "";
          if (!name || seen.has(name)) return;
          seen.add(name);
          stopFeatures.push({
            type: "Feature",
            geometry: { type: "Point", coordinates: [lon, lat] },
            properties: {
              name,
              tier: keyStops[name] ?? 3,
              hi: highlightStops.includes(name),
            },
          });
        });
      });
      map.addSource("stops", {
        type: "geojson",
        data: { type: "FeatureCollection", features: stopFeatures },
      });
      map.addLayer({
        id: "stops", type: "circle", source: "stops",
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            10, ["case", ["get", "hi"], 6, ["==", ["get", "tier"], 1], 4, 2.5],
            15, ["case", ["get", "hi"], 9, ["==", ["get", "tier"], 1], 6, 4],
          ],
          "circle-color": ["case", ["get", "hi"], "#c62828", "#333"],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": ["case", ["get", "hi"], 2, 1],
        },
      });
      // 停留所名: ズーム段階で tier1 → tier2 → 全停留所
      const labelLayer = (id, filter, minzoom, size) => ({
        id, type: "symbol", source: "stops", minzoom, filter,
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": size,
          "text-offset": [0, 1.0],
          "text-anchor": "top",
          "text-optional": false,
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": "#1c1e21",
          "text-halo-color": "#fff",
          "text-halo-width": 1.6,
        },
      });
      map.addLayer(labelLayer("labels1", ["==", ["get", "tier"], 1], 0, 12));
      map.addLayer(labelLayer("labels2", ["==", ["get", "tier"], 2], 12, 11));
      map.addLayer(labelLayer("labels3", ["==", ["get", "tier"], 3], 14, 11));

      map.on("click", "stops", (ev) => {
        new maplibregl.Popup()
          .setLngLat(ev.lngLat)
          .setText(ev.features[0].properties.name)
          .addTo(map);
      });
      if (found) {
        map.fitBounds([[minLon, minLat], [maxLon, maxLat]],
                      { padding: 50, maxZoom: 14, duration: 0 });
      }
    });
  });

  onDestroy(() => map?.remove());
</script>

<div class="map-box" bind:this={container}></div>
<p class="note">
  {tt("legend")}:
  {#each systems as s, i}
    {@const st = styleOf(i)}
    <span style="white-space:nowrap; margin-right:0.8em;">
      <svg width="30" height="8" style="vertical-align:middle">
        <line x1="0" y1="4" x2="30" y2="4" stroke={st.color} stroke-width="3"
              stroke-dasharray={st.dash ? st.dash.map((d) => d * 3).join(",") : ""} />
      </svg>
      {s.first_stop}→{s.last_stop}
      {#if s.status === "added"}[{tt("col_added")}]{/if}
      {#if s.status === "removed"}[{tt("col_removed")}]{/if}
    </span>
  {/each}
</p>
