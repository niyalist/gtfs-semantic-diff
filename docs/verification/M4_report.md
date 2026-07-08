# M4 検証ログ: Markdown レポートと富山地鉄・令和8年4月1日改正の突き合わせ

実施日: 2026-07-04
コマンド: `gtfs-semantic-diff compare --org chitetsu --feed chitetsubus --old prev_2 --new prev_1 --report data/m4_chitetsu_r8_report.md`
対象: prev_2 (2025-10-16〜) → prev_1 (2026-04-01〜, フィード memo「令和８年４月１日ダイヤ改正」)
結果: RawDiff 30,700 件 / explained_ratio 0.9960 / イベント 285 件 / レポート 590 行

## 公式情報との突き合わせ (DoD)

公式告知: [令和8年4月1日 バスダイヤ変更の実施について](https://www.chitetsu.co.jp/?p=81730) (2026-03-11 掲載)

| 公式情報 (出典) | レポートの検出 | 判定 |
|---|---|---|
| 富山港線フィーダーバスの終点を水橋で約300m延伸、新停留所「水橋町」([北日本新聞](https://webun.jp/articles/-/965802)) | `PATTERN_EXTENDED` 富山港線フィーダーバス 平日20便/土日10便 (延伸先: 水橋町) + `STOP_ADDED` 水橋町 + 水橋田町・神明の停留所再編 | ✓ |
| 浜黒崎小学校が 2026-03-31 閉校、跡地に古志はるかぜ学園が 2026-04 開校 ([Wikipedia](https://ja.wikipedia.org/wiki/富山市立古志はるかぜ学園)) | `STOP_RENAMED` 浜黒崎小学校 → 古志はるかぜ学園前 | ✓ |
| 富山ぶりかにバスは季節運行 (2025-10-03〜2026-03-30、[案内](https://www.chitetsu.co.jp/?p=73407)) で4月以降運行なし | `ROUTE_DISCONTINUED` ぶりかにバス線・富山ぶりかにバス + 氷見・新湊系停留所 (ひみ番屋街、海王丸パーク等) の `STOP_REMOVED` ×11 | ✓ (事実として正; 「季節運行終了」への意味昇格は M5 の SEASONAL_SERVICE_CHANGED) |
| ダイヤ変更 (方面別時刻表 PDF で公表) | `SERVICE_REDUCED` ×34 (新幹線市街地線・フィーダー四方・下赤江線ほか、多くが通勤帯 major)、`TIMETABLE_SHIFTED` ×83、`FIRST_LAST_CHANGED` ×11 | ✓ (改正の存在と規模が整合。便単位の照合は時刻表 PDF のため個別確認は未実施) |

主要変更はすべてレポートの「全体サマリ」「主要変更 (major)」に現れており、DoD を満たす。

## レポート構成の確認

architecture.md 通りの5章構成で生成されることを確認:
表紙 (世代・有効期間) / 全体サマリ (異動リスト + 件数表 + major 一覧) /
路線別詳細 (family ごとにイベント・停車パターン変化・時間帯別本数表 旧→新) /
停留所の変更 (一覧表) / データ検証 (explained_ratio、ID churn、残差全件)。

レポートは ChangeEventSet **JSON のみ**から描画される (render_markdown(dict))。
時間帯別本数表のために JSON に `context.band_profiles` (family×方向×day_type×時間帯の
新旧本数) を追加した。events/accounting が正であり context は派生情報。

## 気づき (M5 への入力)

- 残差 124 件 (0.4%): stop_headsign 単独変更・routes_jp 等。M5 の残差追い込み対象。
- ぶりかにバス廃止→季節運行終了の区別には多世代文脈または運行期間メタデータが必要。
- SHAPE_CHANGED が 95 件と多い (shape_id 張り替えを含む疑い)。M5 の Fréchet 局在化で
  「実際に形が変わったか」を判定する。
