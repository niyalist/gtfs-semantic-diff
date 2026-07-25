import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { viteSingleFile } from "vite-plugin-singlefile";
import { fileURLToPath } from "node:url";

// 単一 HTML に全アセットをインライン化する (docs/design/web.md)。
// データはビルド後の index.html 内のプレースホルダ __GTFS_SEMDIFF_DATA__ に
// report/bundle.py が埋め込む。
export default defineConfig(({ mode }) => ({
  plugins: [svelte(), viteSingleFile()],
  resolve: {
    // テストでは maplibre-gl をスタブに (jsdom に WebGL はない。地図は
    // コンポーネントテストの対象外 — ui_quality.md S4)
    alias:
      mode === "test"
        ? {
            "maplibre-gl/dist/maplibre-gl.css": fileURLToPath(
              new URL("./tests/stubs/maplibre-gl.css", import.meta.url)),
            "maplibre-gl": fileURLToPath(
              new URL("./tests/stubs/maplibre-gl.js", import.meta.url)),
          }
        : {},
  },
  build: {
    outDir: "dist",
    cssCodeSplit: false,
    assetsInlineLimit: 100000000,
    chunkSizeWarningLimit: 4000,
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.js"],
    globals: true, // @testing-library/svelte の自動 cleanup に必要
  },
}));
