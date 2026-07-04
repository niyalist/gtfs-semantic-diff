<script>
  import { onMount, onDestroy } from "svelte";
  import maplibregl from "maplibre-gl";
  import "maplibre-gl/dist/maplibre-gl.css";

  export let geometry; // FeatureCollection
  export let baseNames = []; // ハイライトする停留所基底名
  export let shapeIds = []; // ハイライトする shape

  let container;
  let map;

  const STATUS_COLOR = { added: "#0b6e4f", removed: "#c62828", matched: "#7a8391" };

  function relevant() {
    const nameSet = new Set(baseNames);
    const shapeSet = new Set(shapeIds);
    const points = [];
    const lines = [];
    for (const f of geometry.features) {
      if (f.geometry.type === "Point") {
        const hit = nameSet.has(f.properties.base_name);
        points.push({ ...f, properties: { ...f.properties, highlight: hit } });
      } else if (f.geometry.type === "LineString" && shapeSet.has(f.properties.shape_id)) {
        lines.push(f);
      }
    }
    return { points, lines };
  }

  function bounds(features) {
    let minLon = 180, minLat = 90, maxLon = -180, maxLat = -90;
    let found = false;
    for (const f of features) {
      const coords =
        f.geometry.type === "Point" ? [f.geometry.coordinates] : f.geometry.coordinates;
      for (const [lon, lat] of coords) {
        found = true;
        minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
        minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
      }
    }
    return found ? [[minLon, minLat], [maxLon, maxLat]] : null;
  }

  onMount(() => {
    const { points, lines } = relevant();
    map = new maplibregl.Map({
      container,
      style: {
        version: 8,
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
      map.addSource("stops", { type: "geojson", data: { type: "FeatureCollection", features: points } });
      map.addSource("shapes", { type: "geojson", data: { type: "FeatureCollection", features: lines } });
      map.addLayer({
        id: "shapes-old", type: "line", source: "shapes",
        filter: ["==", ["get", "generation"], "old"],
        paint: { "line-color": "#c62828", "line-width": 3, "line-dasharray": [2, 1.5], "line-opacity": 0.8 },
      });
      map.addLayer({
        id: "shapes-new", type: "line", source: "shapes",
        filter: ["==", ["get", "generation"], "new"],
        paint: { "line-color": "#0b6e4f", "line-width": 3, "line-opacity": 0.8 },
      });
      map.addLayer({
        id: "stops-ctx", type: "circle", source: "stops",
        filter: ["!", ["get", "highlight"]],
        paint: {
          "circle-radius": 3,
          "circle-color": ["match", ["get", "status"],
            "added", STATUS_COLOR.added, "removed", STATUS_COLOR.removed, STATUS_COLOR.matched],
          "circle-opacity": 0.35,
        },
      });
      map.addLayer({
        id: "stops-hi", type: "circle", source: "stops",
        filter: ["get", "highlight"],
        paint: {
          "circle-radius": 7,
          "circle-color": ["match", ["get", "status"],
            "added", STATUS_COLOR.added, "removed", STATUS_COLOR.removed, "#0b4f6e"],
          "circle-stroke-color": "#fff", "circle-stroke-width": 2,
        },
      });
      map.on("click", "stops-hi", showPopup);
      map.on("click", "stops-ctx", showPopup);

      const focus = [...points.filter((p) => p.properties.highlight), ...lines];
      const b = bounds(focus.length ? focus : points);
      if (b) map.fitBounds(b, { padding: 50, maxZoom: 15, duration: 0 });
    });

    function showPopup(ev) {
      const f = ev.features[0];
      new maplibregl.Popup()
        .setLngLat(ev.lngLat)
        .setHTML(
          `<strong>${f.properties.name}</strong><br/>` +
            `${f.properties.status} / ${f.properties.platforms} platform(s)`
        )
        .addTo(map);
    }
  });

  onDestroy(() => map?.remove());
</script>

<div class="map-box" bind:this={container}></div>
