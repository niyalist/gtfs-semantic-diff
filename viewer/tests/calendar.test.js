// 特定日カレンダー (2026-07-29 仕様) と年付きラン列挙のテスト
import { describe, expect, test } from "vitest";
import { render } from "@testing-library/svelte";
import DateCalendar from "../src/components/DateCalendar.svelte";
import { runsText } from "../src/lib/format.js";

describe("runsText withYear (短い列挙に年を付ける)", () => {
  test("先頭と年替わりにだけ年を前置", () => {
    const runs = [["20250426", "20250426"], ["20250502", "20250506"],
                  ["20260104", "20260106"]];
    expect(runsText(runs, 0, 8, "ja", { withYear: true }))
      .toBe("2025/4/26、5/2〜5/6、2026/1/4〜1/6 (全8日)");
    expect(runsText(runs, 0, 8, "en", { withYear: true }))
      .toBe("2025/4/26, 5/2–5/6, 2026/1/4–1/6 (8 days)");
  });
  test("withYear なしは従来どおり (第1部 sdn 等の互換)", () => {
    expect(runsText([["20250426", "20250426"]], 0, null, "ja")).toBe("4/26");
  });
});

describe("DateCalendar", () => {
  // 北海道中央バスの実例 (旧15日/新22日、4〜6月)
  const oldRuns = [["20250426", "20250426"], ["20250429", "20250429"],
                   ["20250502", "20250506"], ["20250509", "20250510"],
                   ["20250516", "20250517"], ["20250523", "20250524"],
                   ["20250530", "20250531"]];
  const newRuns = [["20250404", "20250405"], ["20250411", "20250412"],
                   ["20250418", "20250419"], ["20250425", "20250426"],
                   ["20250429", "20250429"], ["20250502", "20250506"],
                   ["20250509", "20250510"], ["20250516", "20250517"],
                   ["20250523", "20250524"], ["20250530", "20250531"],
                   ["20250606", "20250607"]];

  test("対象範囲の全月を描画し、日曜始まりで正しい位置に日が入る", () => {
    const { container } = render(DateCalendar, { oldRuns, newRuns });
    const months = container.querySelectorAll(".cal-month");
    expect(months.length).toBe(3); // 2025年4月〜6月
    expect(months[0].querySelector("caption").textContent).toBe("2025年4月");
    // 2025-04-01 は火曜 → 第1週の3列目 (日月火)
    const firstWeek = months[0].querySelectorAll("tbody tr")[0];
    const cells = firstWeek.querySelectorAll("td");
    expect(cells[0].textContent.trim()).toBe("");
    expect(cells[2].textContent.trim()).toBe("1");
  });

  test("旧のみ=取り消し線 / 新のみ=下線 / 両方=素の数字 (記号第1チャネル)", () => {
    const { container } = render(DateCalendar, { oldRuns, newRuns });
    const byDate = {};
    container.querySelectorAll(".cal-month").forEach((mo) => {
      const month = mo.querySelector("caption").textContent;
      mo.querySelectorAll("td").forEach((td) => {
        const d = td.textContent.trim();
        if (d) byDate[`${month}-${d}`] = td;
      });
    });
    // 4/26 は両方 → both クラス・装飾なし数字
    expect(byDate["2025年4月-26"].className).toContain("both");
    expect(byDate["2025年4月-26"].querySelector("s, u")).toBeNull();
    // 4/4 は新のみ → 下線
    expect(byDate["2025年4月-4"].className).toContain("new");
    expect(byDate["2025年4月-4"].querySelector("u")).not.toBeNull();
    // 運行なしの日は無装飾
    expect(byDate["2025年4月-1"].className).not.toMatch(/both|old|new/);
  });

  test("旧のみの日は取り消し線 (片側が消えた例)", () => {
    const { container } = render(DateCalendar, {
      oldRuns: [["20250426", "20250427"]], newRuns: [["20250427", "20250427"]],
    });
    const tds = [...container.querySelectorAll("td")]
      .filter((td) => td.textContent.trim() === "26");
    expect(tds[0].className).toContain("old");
    expect(tds[0].querySelector("s")).not.toBeNull();
  });
});
