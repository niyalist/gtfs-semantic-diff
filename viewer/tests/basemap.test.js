// I4: 基図選択の純ロジック (docs/design/i18n.md I4)
import { beforeEach, describe, expect, test } from "vitest";
import { BASEMAPS, defaultBasemap, inJapan } from "../src/lib/basemap.js";

// 実行環境に localStorage が無い場合に備えた最小スタブ
// (basemap.js は呼び出し時に参照するため、ここでの差し替えで足りる)
if (!globalThis.localStorage) {
  const m = new Map();
  globalThis.localStorage = {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
  };
}

beforeEach(() => localStorage.removeItem("basemap"));

describe("basemap 選択", () => {
  test("日本域は地理院、国外は OSM、座標不明は地理院", () => {
    expect(inJapan(36.0, 139.0)).toBe(true);      // 関東
    expect(inJapan(43.0, 141.3)).toBe(true);      // 札幌
    expect(inJapan(45.5, -122.7)).toBe(false);    // ポートランド
    expect(inJapan(41.9, 12.5)).toBe(false);      // ローマ
    expect(defaultBasemap(36.0, 139.0)).toBe("gsi");
    expect(defaultBasemap(45.5, -122.7)).toBe("osm");
    expect(defaultBasemap(null, null)).toBe("gsi");
  });

  test("利用者の保存済み選択が自動判定に勝つ", () => {
    localStorage.setItem("basemap", "osm");
    expect(defaultBasemap(36.0, 139.0)).toBe("osm");
    localStorage.setItem("basemap", "nonsense");
    expect(defaultBasemap(36.0, 139.0)).toBe("gsi");  // 不正値は無視
  });

  test("基図は両言語のラベルと出典表記を持つ", () => {
    for (const b of Object.values(BASEMAPS)) {
      expect(b.label.ja && b.label.en).toBeTruthy();
      expect(b.source.attribution).toBeTruthy();
    }
  });
});
