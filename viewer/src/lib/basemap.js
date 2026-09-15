// I4: 基図の抽象化 (docs/design/i18n.md I4)。
// 既定は座標で自動 (日本域 = 地理院 pale / 国外 = OSM 標準ラスタ)。
// 利用者はレイヤ切替ボタンで上書きでき、選択は localStorage "basemap" に
// 保存して全地図・全レポートで共有する。
// OSM ラスタは国際対応の繋ぎ (終着は RD3/PMTiles の自前配信 —
// tile.openstreetmap.org の利用ポリシーを踏まえ、地図を開いたときだけの
// 軽負荷に留める)。基図の実体はラスタ2種のみ: setStyle を使わず
// レイヤ/ソースの差し替えだけで切り替えるため、路線・停留所の
// オーバーレイには一切触れない。
export const BASEMAPS = {
  gsi: {
    label: { ja: "地理院", en: "GSI" },
    source: {
      type: "raster",
      tiles: ["https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "国土地理院",
    },
  },
  osm: {
    label: { ja: "OSM", en: "OSM" },
    source: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
};

export function inJapan(lat, lon) {
  return lat >= 20 && lat <= 46 && lon >= 122 && lon <= 154;
}

export function storedBasemap() {
  try {
    const v = localStorage.getItem("basemap");
    return v && v in BASEMAPS ? v : null;
  } catch {
    return null;
  }
}

// 初期基図: 利用者の保存済み選択 > 座標による自動判定 > 地理院
export function defaultBasemap(lat, lon) {
  return storedBasemap()
    ?? (lat == null || lon == null || inJapan(lat, lon) ? "gsi" : "osm");
}

export function baseStyle(kind, { glyphs } = {}) {
  return {
    version: 8,
    ...(glyphs ? { glyphs } : {}),
    sources: { [kind]: BASEMAPS[kind].source },
    layers: [{ id: `base-${kind}`, type: "raster", source: kind }],
  };
}

// 基図レイヤだけを最背面で差し替える (オーバーレイ不変)。選択は保存する
export function switchBasemap(map, kind) {
  for (const k of Object.keys(BASEMAPS)) {
    if (k === kind) continue;
    if (map.getLayer(`base-${k}`)) map.removeLayer(`base-${k}`);
    if (map.getSource(k)) map.removeSource(k);
  }
  if (!map.getSource(kind)) map.addSource(kind, BASEMAPS[kind].source);
  if (!map.getLayer(`base-${kind}`)) {
    const first = map.getStyle().layers[0];
    map.addLayer({ id: `base-${kind}`, type: "raster", source: kind },
                 first ? first.id : undefined);
  }
  try {
    localStorage.setItem("basemap", kind);
  } catch { /* private mode 等 */ }
}
