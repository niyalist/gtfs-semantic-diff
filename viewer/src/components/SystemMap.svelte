<script>
  import { onMount, onDestroy } from "svelte";
  import maplibregl from "maplibre-gl";
  import "maplibre-gl/dist/maplibre-gl.css";
  import { t } from "../lib/i18n.js";

  // R2 改: 描画単位は leg (時刻表単位・曜日統合)。
  // 各 leg は極大パターンの線集合 (lines) を持ち、同色・同レーンで重ね描きする —
  // 幹線はぴったり重なって1本に見え、分岐点から自然に枝が分かれる。
  // 凡例・ラベルは③本数表の方向行・④時刻表の表題と同一語彙 (leg.label)。
  export let legs = []; // [{leg, label, status, lines: [{stops, polyline}], ...}]
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
      // オフセット = 「進行方向の右側レーン」方式。leg ごとにページ内で一意の
      // レーン番号 (1始まり)。往復 leg は進行方向が逆なので自動的に反対側へ並び、
      // 循環 leg の折り返し区間も左右に分かれる。leg 内の極大パターン線は
      // 同一レーンなので幹線が完全に重なって1本に見える (それが狙い)。
      const zoomExpr = (v10, v13, v15, v17) => [
        "interpolate", ["linear"], ["zoom"], 10, v10, 13, v13, 15, v15, 17, v17,
      ];
      const entries = [];
      legs.forEach((lg, i) => {
        const lineCoords = (lg.lines || []).map((ln) =>
          (ln.polyline || [])
            .map(([lat, lon]) => [lon, lat])
            // 連続する同一座標を除去 (offset 計算の乱れ防止)
            .filter((c, k, arr) => k === 0 || c[0] !== arr[k - 1][0] || c[1] !== arr[k - 1][1])
        ).filter((cs) => cs.length >= 2);
        if (!lineCoords.length) return;
        for (const cs of lineCoords) {
          for (const [lon, lat] of cs) {
            found = true;
            minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
            minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
          }
        }
        const removed = lg.status === "removed";
        entries.push({
          i,
          removed,
          ...styleOf(i),
          width: removed ? zoomExpr(2.5, 4, 6, 9) : zoomExpr(3.5, 6, 9, 14),
          offset: zoomExpr((i + 1) * 1.8, (i + 1) * 4, (i + 1) * 6.5, (i + 1) * 10),
        });
        map.addSource(`leg${i}`, {
          type: "geojson",
          data: {
            type: "Feature",
            geometry: { type: "MultiLineString", coordinates: lineCoords },
          },
        });
      });
      // 描画は3段: (1) 全 leg の白縁取りを先に敷く → 隣のレーンの線を縁取りが
      // 上書きしない (2) 本体の色線 (3) 縞・白芯のオーバーレイ
      for (const e of entries) {
        map.addLayer({
          id: `leg${e.i}-casing`, type: "line", source: `leg${e.i}`,
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
          id: `leg${e.i}`, type: "line", source: `leg${e.i}`,
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
            id: `leg${e.i}-stripe`, type: "line", source: `leg${e.i}`,
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
            id: `leg${e.i}-core`, type: "line", source: `leg${e.i}`,
            paint: {
              "line-color": CORE_COLOR,
              "line-width": e.removed ? zoomExpr(0.9, 1.4, 2.1, 3.2) : zoomExpr(1.2, 2, 3, 4.7),
              "line-offset": e.offset,
              "line-opacity": opacity,
            },
          });
        }
      }

      // 停留所点 + tier 付きラベル。tier1 (起終点・ハブ) / tier2 (区間便の端点・
      // 分岐点 = 時刻表内で出発・終着・分離が起こる停留所) は白抜きの大きい丸で強調
      const stopFeatures = [];
      const seen = new Set();
      legs.forEach((lg) => {
        (lg.lines || []).forEach((ln) => {
          (ln.polyline || []).forEach(([lat, lon], idx) => {
            const name = ln.stops[idx] ?? "";
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
            10, ["case", ["get", "hi"], 7,
                 ["==", ["get", "tier"], 1], 6,
                 ["==", ["get", "tier"], 2], 4.5, 2.5],
            15, ["case", ["get", "hi"], 10,
                 ["==", ["get", "tier"], 1], 9,
                 ["==", ["get", "tier"], 2], 7, 4],
          ],
          // 主要停留所 (tier1/2) は白抜き+濃輪郭、その他は濃点+白輪郭
          "circle-color": ["case",
            ["get", "hi"], "#c62828",
            ["<=", ["get", "tier"], 2], "#fff", "#333"],
          "circle-stroke-color": ["case",
            ["get", "hi"], "#fff",
            ["<=", ["get", "tier"], 2], "#1c1e21", "#fff"],
          "circle-stroke-width": ["case",
            ["get", "hi"], 2,
            ["<=", ["get", "tier"], 2], 2, 1],
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
      map.addLayer(labelLayer("labels2", ["==", ["get", "tier"], 2], 11, 11.5));
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
  {#each legs as lg, i}
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
      {lg.label}
      {#if lg.status === "added"}[{tt("col_added")}]{/if}
      {#if lg.status === "removed"}[{tt("col_removed")}]{/if}
    </span>
  {/each}
</p>
