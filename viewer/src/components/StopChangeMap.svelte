<script>
  import { onMount, onDestroy } from "svelte";
  import maplibregl from "maplibre-gl";
  import "maplibre-gl/dist/maplibre-gl.css";
  import { t } from "../lib/i18n.js";

  export let changes; // presentation.stop_changes

  let container;
  let map;
  $: tt = $t;

  // 種別の第1チャネルはラベル接頭辞 (【改称】等)。色は補強 (原則5)
  const COLORS = {
    renamed: "#0072B2",
    relocated: "#7B3294",
    added: "#008A5E",
    removed: "#B0004E",
  };

  onMount(() => {
    map = new maplibregl.Map({
      container,
      style: {
        version: 8,
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
      const feats = [];
      const moveLines = [];
      let minLon = 180, minLat = 90, maxLon = -180, maxLat = -90, found = false;
      const pfx = (key) => `【${tt(key)}】`;
      const push = (kind, lat, lon, label) => {
        if (lat == null || lon == null) return;
        found = true;
        minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
        minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
        feats.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: [lon, lat] },
          properties: { kind, label },
        });
      };
      changes.renamed.forEach((r) =>
        push("renamed", r.lat, r.lon, `${pfx("sc_renamed")}${r.old_name}→${r.new_name}`));
      changes.relocated.forEach((r) => {
        push("relocated", r.lat, r.lon, `${pfx("sc_relocated")}${r.name}`);
        if (r.old_lat != null && r.old_lon != null && r.lat != null && r.lon != null)
          moveLines.push([[r.old_lon, r.old_lat], [r.lon, r.lat]]);
      });
      changes.added.forEach((g) => g.stops.forEach((s) =>
        push("added", s.lat, s.lon, `${pfx("sc_added")}${s.name}`)));
      changes.removed.forEach((g) => g.stops.forEach((s) =>
        push("removed", s.lat, s.lon, `${pfx("sc_removed")}${s.name}`)));

      // 移設の旧→新 (破線)
      if (moveLines.length) {
        map.addSource("moves", {
          type: "geojson",
          data: { type: "Feature",
                  geometry: { type: "MultiLineString", coordinates: moveLines } },
        });
        map.addLayer({
          id: "moves", type: "line", source: "moves",
          paint: { "line-color": COLORS.relocated, "line-width": 2.5,
                   "line-dasharray": [2, 2] },
        });
      }
      map.addSource("pts", {
        type: "geojson",
        data: { type: "FeatureCollection", features: feats },
      });
      map.addLayer({
        id: "pts", type: "circle", source: "pts",
        paint: {
          "circle-radius": 6.5,
          "circle-color": ["match", ["get", "kind"],
            "renamed", COLORS.renamed,
            "relocated", COLORS.relocated,
            "added", COLORS.added,
            COLORS.removed],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      // 件数は少ないのでラベルは常時表示 (接頭辞【改称】等が種別の第1チャネル)
      map.addLayer({
        id: "pt-labels", type: "symbol", source: "pts",
        layout: {
          "text-field": ["get", "label"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11.5,
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
      if (found) {
        map.fitBounds([[minLon, minLat], [maxLon, maxLat]],
                      { padding: 60, maxZoom: 15, duration: 0 });
      }
    });
  });

  onDestroy(() => map?.remove());
</script>

<div class="map-box" bind:this={container}></div>
<p class="note">{tt("sc_map_legend")}</p>
