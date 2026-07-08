import App from "./App.svelte";
import "./app.css";

// データ解決: (1) 埋め込み JSON (単一ファイル配布) → (2) ./bundle.json (ホスト配信/開発)
function embedded() {
  const el = document.getElementById("gtfs-semantic-diff-data");
  if (!el) return null;
  const text = el.textContent.trim();
  if (!text || text.startsWith("__GTFS_SEMDIFF")) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function start() {
  let bundle = embedded();
  if (!bundle) {
    try {
      const res = await fetch("./bundle.json");
      if (res.ok) bundle = await res.json();
    } catch {
      /* データなしで起動 (App がメッセージを出す) */
    }
  }
  new App({ target: document.getElementById("app"), props: { bundle } });
}

start();
