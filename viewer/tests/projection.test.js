// 表示射影のスナップショット (ui_quality.md S4)。
// 「ユーザーが読む文字列」を固定し、サーバー/ビューアどちらの変更でも
// 表示の変化が diff として見えるようにする
import { expect, test } from "vitest";
import { projectPresentation } from "../src/lib/projection.js";
import { fixturePresentation } from "./fixtures.js";

test("表示射影 (ja)", () => {
  expect(projectPresentation(fixturePresentation(), "ja")).toMatchSnapshot();
});

test("表示射影 (en)", () => {
  expect(projectPresentation(fixturePresentation(), "en")).toMatchSnapshot();
});
