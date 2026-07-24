// 検証モード → レポート項目へのジャンプ (RD1a)。
// target: {part: 1|2|4} または {part: 3, route_group}
import { writable } from "svelte/store";

export const jumpTarget = writable(null);

let seq = 0;
export function jumpTo(target) {
  jumpTarget.set({ ...target, seq: ++seq }); // 同一 target の再クリックも発火させる
}

export function anchorId(target) {
  return target.part === 3 ? `route-${target.route_group}` : `part${target.part}`;
}
