// テスト用スタブ (vite.config.js の test モード alias)。jsdom に WebGL はなく、
// 地図はコンポーネントテストの対象外 (ui_quality.md S4)
export default {
  Map: class {
    on() {}
    remove() {}
    addControl() {}
  },
  NavigationControl: class {},
  LngLatBounds: class {
    extend() { return this; }
  },
  Marker: class {
    setLngLat() { return this; }
    addTo() { return this; }
    remove() {}
  },
  Popup: class {
    setLngLat() { return this; }
    setHTML() { return this; }
    addTo() { return this; }
  },
};
