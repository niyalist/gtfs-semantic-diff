// I3 (i18n.md §6): en モード DOM の CJK 機械監査。
// フィクスチャ (en_bundle.json) は停留所・路線名がすべて英語の合成フィード
// から生成した実 bundle (scripts/gen_i18n_en_fixture.py で再生成)。
// データが英語なので「DOM に CJK が現れる = 当方の焼き込み」が成立し、
// 許容リストなしで翻訳漏れを検出できる。
// 唯一の例外は言語トグルの「日本語」ボタン (.lang-toggle) で、走査から除外する。
import { describe, expect, test } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import { lang } from "../src/lib/i18n.js";
import App from "../src/App.svelte";
import bundle from "./fixtures/en_bundle.json";

lang.set("en");

const CJK = /[ぁ-んァ-ヶ一-鿿々〜、。「」・【】]/;

function cjkLeaks(container) {
  const leaks = [];
  const walk = (node) => {
    if (node.nodeType === 3) {
      const text = node.textContent.trim();
      // 「・・」(通らない停留所の印) は言語共通の記号 — 単独ノードのみ許容
      if (text !== "・・" && CJK.test(node.textContent)) {
        leaks.push(text.slice(0, 80));
      }
      return;
    }
    if (node.classList?.contains("lang-toggle")) return; // 「日本語」ボタン
    for (const child of node.childNodes) walk(child);
  };
  walk(container);
  return leaks;
}

describe("en モードの CJK 監査 (App 全体)", () => {
  test("レポートモードに日本語が現れない", () => {
    const { container } = render(App, { bundle });
    expect(cjkLeaks(container)).toEqual([]);
  });

  test("検証モードに日本語が現れない", async () => {
    const { container, getAllByRole } = render(App, { bundle });
    const verifyBtn = getAllByRole("button").find((b) =>
      /verif/i.test(b.textContent));
    expect(verifyBtn).toBeTruthy();
    await fireEvent.click(verifyBtn);
    expect(cjkLeaks(container)).toEqual([]);
  });

  test("ja へ切り替えると日本語 UI に戻る (再マウント経路の回帰)", async () => {
    const { container } = render(App, { bundle });
    lang.set("ja");
    await new Promise((r) => setTimeout(r, 0));
    expect(container.textContent).toContain("路線毎の変化");
    lang.set("en"); // 後続テストのために戻す
  });
});
