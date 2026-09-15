// 表示整形の純関数テスト (ui_quality.md S4)。PI-1/PI-2/PI-3 の実装を固定する
import { describe, expect, test } from "vitest";
import { countText, runsText } from "../src/lib/format.js";
import { dayName, formatDateRuns, partsLabel, translator } from "../src/lib/i18n.js";

const tt = translator("ja");

describe("countText (PI-1/PI-2: 便数表記の一元実装)", () => {
  test("変化なし", () => {
    expect(countText(tt, { old: 16, new: 16 })).toBe("16便");
  });
  test("増減 (▲▼が第1チャネル)", () => {
    expect(countText(tt, { old: 16, new: 12 })).toBe("16→12便▼");
    expect(countText(tt, { old: 12, new: 16 })).toBe("12→16便▲");
  });
  test("mixed 側は「のべ」を冠する (立川 A2 の再発防止)", () => {
    expect(countText(tt, { old: 28, new: 16, mixed_old: true })).toBe(
      "のべ28便→16便▼"
    );
  });
  test("同数でも mixed なら のべ", () => {
    expect(countText(tt, { old: 28, new: 28, mixed_old: true })).toBe("のべ28便");
  });
});

describe("runsText (PI-3: 日付ラン表示の一元実装)", () => {
  test("ラン+全日数", () => {
    expect(runsText([["20260301", "20261031"]], 0, 245, "ja")).toBe(
      "3/1〜10/31 (全245日)"
    );
  });
  test("年境で分割されたランの列挙", () => {
    expect(
      runsText([["20261101", "20261231"], ["20270101", "20270228"]], 0, 120, "ja")
    ).toBe("11/1〜12/31、1/1〜2/28 (全120日)");
  });
  test("あふれ区間", () => {
    expect(runsText([["20260704", "20260704"]], 3, 4, "ja")).toBe(
      "7/4 ほか3区間 (全4日)"
    );
  });
});

describe("formatDateRuns (旧版バンドル互換のクライアント側圧縮)", () => {
  test("連続日は月を跨いで繋げ、年境のみ分割 (PI-3)", () => {
    const r = formatDateRuns(
      ["20261230", "20261231", "20270101", "20270102"], "ja");
    expect(r.text).toBe("12/30〜12/31、1/1〜1/2");
    expect(r.more).toBe(0);
  });
  test("月跨ぎは1本のラン", () => {
    expect(formatDateRuns(["20260331", "20260401"], "ja").text).toBe("3/31〜4/1");
  });
});

describe("dayName", () => {
  test("世界セルラベル @N は丸数字", () => {
    expect(dayName("saturday@2", "ja")).toBe("土曜②");
    expect(dayName("daily@1", "ja")).toBe("毎日①");
  });
  test("dow_ は曜日集合から生成", () => {
    expect(dayName("dow_1010100", "ja")).toBe("月・水・金曜");
  });
});

// --- I3: partsLabel (生成ラベルの en 組み立て / ja 不変) ---
describe("partsLabel (I3)", () => {
  const cases = [
    ["駅前 循環", { kind: "loop", stop: "駅前" }, "駅前 loop"],
    ["駅前 循環（停あ先回り）", { kind: "loop_dir", stop: "駅前", first: "停あ" },
     "駅前 loop (停あ first)"],
    ["A・B経由", { kind: "via", stops: ["A", "B"] }, "via A / B"],
    ["市役所前先回り", { kind: "first", stop: "市役所前" }, "市役所前 first"],
    ["経路2", { kind: "route_n", n: 2 }, "Route 2"],
    ["駅前 循環（2）", { kind: "loop", stop: "駅前", dup: 2 }, "駅前 loop (2)"],
  ];
  test("en は parts から組み立てる", () => {
    for (const [ja, parts, en] of cases) {
      expect(partsLabel(ja, parts, "en")).toBe(en);
    }
  });
  test("ja は焼き込みラベルをそのまま返す (表示不変)", () => {
    for (const [ja, parts] of cases) {
      expect(partsLabel(ja, parts, "ja")).toBe(ja);
    }
  });
  test("parts が無ければ言語によらずラベルをそのまま返す", () => {
    expect(partsLabel("駅前 → 病院前", null, "en")).toBe("駅前 → 病院前");
    expect(partsLabel("駅前 → 病院前", undefined, "ja")).toBe("駅前 → 病院前");
  });
});

// --- I4: 運賃の通貨表示 (円決め打ちの解消) ---
describe("fo_price (I4)", () => {
  const ja = translator("ja");
  const en = translator("en");
  test("未指定・JPY は従来どおり (ja 表示不変)", () => {
    expect(ja("fo_price", undefined, 220, 250)).toBe("220円→250円");
    expect(ja("fo_price", "JPY", 220, 250)).toBe("220円→250円");
    expect(en("fo_price", "JPY", 220, 250)).toBe("¥220→¥250");
  });
  test("USD/EUR は記号、未知コードはコード後置", () => {
    expect(ja("fo_price", "USD", "2.50", "2.80")).toBe("$2.50→$2.80");
    expect(en("fo_price", "EUR", "1.50", "2.00")).toBe("€1.50→€2.00");
    expect(en("fo_price", "CAD", "3.25", "3.50")).toBe("3.25→3.50 CAD");
  });
  test("複数通貨 (配列) は先頭を使う", () => {
    expect(en("fo_price", ["USD", "CAD"], 1, 2)).toBe("$1→$2");
  });
});
