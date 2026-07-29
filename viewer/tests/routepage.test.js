// RoutePage のコンポーネントテスト (ui_quality.md S4)。
// しんぐうバグ (タブ切替で日付が再描画されない — Svelte リアクティビティ) と
// 立川バグ (折りたたみヘッダが mixed を知らない) の再発防止
import { describe, expect, test } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import RoutePage from "../src/components/RoutePage.svelte";
import { shinguPage, tachikawaPage } from "./fixtures.js";

describe("RoutePage 曜日タブ (SD5b セル)", () => {
  test("タブ切替でセルの日付注記が更新される (しんぐう回帰)", async () => {
    const { getByRole, container } = render(RoutePage, {
      page: shinguPage(), index: "3.1", open: true,
    });
    const note = () => container.querySelector(".special-dates").textContent;
    const firstMonth = () =>
      container.querySelector(".cal-month caption").textContent;
    // 初期タブ = 毎日① (春夏)。245日 ≥ 10日なのでカレンダーモード
    // (2026-07-29 仕様: 列挙の代わりに全日数+カレンダー)
    expect(note()).toContain("全245日");
    expect(firstMonth()).toBe("2025年3月");
    // 毎日② へ切替 → 秋冬 (120日・11月始まり) に変わること
    await fireEvent.click(getByRole("tab", { name: /毎日②/ }));
    expect(note()).toContain("全120日");
    expect(note()).not.toContain("全245日");
    expect(firstMonth()).toBe("2025年11月");
  });

  test("mixed セルは折りたたみヘッダも「のべ」 (立川 A2 回帰)", () => {
    const { container } = render(RoutePage, {
      page: tachikawaPage(), index: "3.3", open: false,
    });
    const summary = container.querySelector("summary").textContent;
    expect(summary).toContain("のべ28便→16便▼");
    expect(summary).not.toContain("特定日① 28→16");
  });

  test("mixed タブに ⚠ 注記と共有日が出る (SD5c 案C)", () => {
    const { getByRole, container } = render(RoutePage, {
      page: tachikawaPage(), index: "3.3", open: true,
    });
    expect(getByRole("tab", { name: /のべ28便→16便▼/ })).toBeTruthy();
    const note = container.querySelector(".special-dates").textContent;
    expect(note).toContain("⚠");
    expect(note).toContain("2/28");
  });
});
