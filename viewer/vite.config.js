import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { viteSingleFile } from "vite-plugin-singlefile";

// 単一 HTML に全アセットをインライン化する (docs/design/web.md)。
// データはビルド後の index.html 内のプレースホルダ __GTFS_SEMDIFF_DATA__ に
// report/bundle.py が埋め込む。
export default defineConfig({
  plugins: [svelte(), viteSingleFile()],
  build: {
    outDir: "dist",
    cssCodeSplit: false,
    assetsInlineLimit: 100000000,
    chunkSizeWarningLimit: 4000,
  },
});
