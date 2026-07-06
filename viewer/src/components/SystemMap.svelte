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

  // 原則5: 色 + 線デザインの二重チャネル。凡例にも同じ組を出す。
  // 点線 (途切れる線) は使わない — 線は常に連続させ、バリエーションは
  //   solid: 単色線 / stripe: 同幅の濃灰ダッシュを重ねた2色縞 / double: 細い白芯の二本線
  // で出す。色は色弱対応の濃色に絞る (Okabe-Ito 系を暗めに調整、5色 × 3デザイン = 15組)。
  const PALETTE = ["#0072B2", "#D55E00", "#008A5E", "#7B3294", "#B0004E"];
  const PATTERNS = ["solid", "stripe", "double"];
  const STRIPE_COLOR = "#333"; // 縞の第2色。白は縁取りと同化して途切れて見えるため濃色
  const CORE_COLOR = "#fff";

  export function styleOf(i) {
    return { color: PALETTE[i % PALETTE.length], pattern: PATTERNS[i % PATTERNS.length] };
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
      const zoomExpr = (v10, v13, v15, v17) => [
        "interpolate", ["linear"], ["zoom"], 10, v10, 13, v13, 15, v15, 17, v17,
      ];
      const entries = [];
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
        const removed = s.status === "removed";
        entries.push({
          i,
          removed,
          ...styleOf(i),
          // 線幅: ズーム連動を強めに (拡大時に細すぎる問題への対応)
          width: removed ? zoomExpr(2.5, 4, 6, 9) : zoomExpr(3.5, 6, 9, 14),
          offset: zoomExpr(laneOf[i] * 1.8, laneOf[i] * 4, laneOf[i] * 6.5, laneOf[i] * 10),
        });
        map.addSource(`sys${i}`, {
          type: "geojson",
          data: { type: "Feature", geometry: { type: "LineString", coordinates: coords } },
        });
      });
      // 描画は3段: (1) 全系統の白縁取りを先に敷く → 隣のレーンの線を縁取りが
      // 上書きしない (2) 本体の色線 (3) 縞・白芯のオーバーレイ
      for (const e of entries) {
        map.addLayer({
          id: `sys${e.i}-casing`, type: "line", source: `sys${e.i}`,
          paint: {
            "line-color": "#fff",
            // 縁取り: 本体より片側 1.5〜3px 太く。地図 (特に拡大時) とのコントラスト確保
            "line-width": e.removed
              ? zoomExpr(5.5, 7.5, 10, 14.5)
              : zoomExpr(6.5, 9.5, 13.5, 19.5),
            "line-offset": e.offset,
            "line-opacity": e.removed ? 0.75 : 1,
          },
        });
      }
      for (const e of entries) {
        const opacity = e.removed ? 0.75 : 1;
        map.addLayer({
          id: `sys${e.i}`, type: "line", source: `sys${e.i}`,
          paint: {
            "line-color": e.color,
            "line-width": e.width,
            "line-offset": e.offset,
            "line-opacity": opacity,
          },
        });
        if (e.pattern === "stripe") {
          // 同幅のダッシュを重ねる → 下の色線が隙間を埋め、途切れない2色縞になる
          map.addLayer({
            id: `sys${e.i}-stripe`, type: "line", source: `sys${e.i}`,
            paint: {
              "line-color": STRIPE_COLOR,
              "line-width": e.width,
              "line-offset": e.offset,
              "line-opacity": opacity,
              "line-dasharray": [1.6, 1.6],
            },
          });
        } else if (e.pattern === "double") {
          // 細い白芯を重ねて二本線に
          map.addLayer({
            id: `sys${e.i}-core`, type: "line", source: `sys${e.i}`,
            paint: {
              "line-color": CORE_COLOR,
              "line-width": e.removed ? zoomExpr(0.9, 1.4, 2.1, 3.2) : zoomExpr(1.2, 2, 3, 4.7),
              "line-offset": e.offset,
              "line-opacity": opacity,
            },
          });
        }
      }

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
      <!-- 背景が白なので、地図の白縁取りの代わりに淡灰の帯で白芯を見せる -->
      <svg width="34" height="10" style="vertical-align:middle">
        <line x1="0" y1="5" x2="34" y2="5" stroke="#d5d5d5" stroke-width="9" />
        <line x1="0" y1="5" x2="34" y2="5" stroke={st.color} stroke-width="6" />
        {#if st.pattern === "stripe"}
          <line x1="0" y1="5" x2="34" y2="5" stroke="#333" stroke-width="6"
                stroke-dasharray="6,6" />
        {:else if st.pattern === "double"}
          <line x1="0" y1="5" x2="34" y2="5" stroke="#fff" stroke-width="2" />
        {/if}
      </svg>
      {s.first_stop}→{s.last_stop}
      {#if s.status === "added"}[{tt("col_added")}]{/if}
      {#if s.status === "removed"}[{tt("col_removed")}]{/if}
    </span>
  {/each}
</p>
