# 運行日パターン調査 — SD5/SD6 (運行日世界・レジーム整列) 検討用データセット (2026-07-25)

目的: PRT の特定日合算誤り・bus-vision 世代同居の再発見 (2026-07-25 振り返り) を
一般解 (原則A「同じ日に走らないものを足さない」/ 原則B「レジーム切替点で整列」)
に落とす前に、世の中の運行日表現パターンを広く観測し、設計の当たり判定を行う。

手段: `scripts/survey_day_patterns.py` — calendar / calendar_dates / feed_info
だけを読む軽量分類器。タグ:

| タグ | 意味 | 設計上の論点 |
|---|---|---|
| dow_odd | 変則曜日フラグ (月水金等、標準6種以外) | dow_* 一級化 (M10) の適用範囲 |
| mixed_expiry | service 毎に有効期限がバラバラ (寄せ集め) | 窓・レジームの定義が service 単位で割れる |
| cd_only | calendar なし・calendar_dates のみ | 実効運行日集合が唯一の真実 (規則が無い) |
| holiday_cd | cd_only かつ追加 1〜5 日 (祝日専用の素朴型) | 原則A: 互いに素な特定日世界 |
| holiday_flagged | フラグあり + 削除希釈で実効 ≤5 日 (PRT 型) | 同上 (SD1 密度判定の対象) |
| seasonal_split | 同一フラグの期間分割 (STM 型 / **世代同居も構造上同型**) | 原則B: レジームか季節か同居かの判別 |
| swap_dates | 同日に運休+代替 (日本の祝日振替standard) | 現行の「日曜ダイヤで運行」説明の裏付け |
| school_kw | service_id に 学/校/休業等 (学校日ダイヤ) | 平日の下位分割 (ラベル語彙への挑戦) |

## 手持ちデータの分類結果 (2026-07-25、分類器の妥当性確認を兼ねる)

| データ | タグ | 特記 |
|---|---|---|
| PRT 新 (米・都市) | dow_odd, holiday_flagged, seasonal_split | 祝日 service が互いに素 (7/4 と 9/7) = 発端事例。四半期の期間分割も併存 |
| STM (加・都市) | dow_odd, **mixed_expiry** | 終端が 14 種・149 日散らばる (寄せ集め度は想定以上)。金曜のみ service |
| ovapi_nl (蘭・全国) | cd_only, holiday_cd | calendar 行ゼロ・calendar_dates 40万行。cd_only 4,301 service |
| 佐賀県 (集約) | cd_only, holiday_cd, swap_dates, **school_kw** | 「4_学休ダイヤ」既収蔵。年末年始 cd_only。振替 66 日 |
| 三重交通桑名 0710 (bus-vision 同居) | seasonal_split | **世代同居が季節分割と同じタグに落ちる** = SD2/T3 判別問題の構造的確認 |
| 名古屋市バス | dow_odd, swap_dates | 平日メーグル = 火〜金 (0111100)。振替 25 日 |
| LA Metro (米・大都市) | dow_odd, cd_only, holiday_cd, holiday_flagged, swap_dates | **通学ダイヤの宝庫**: service_id に高校名 (LINCHS1 等)、火のみ/月水木金の対、平日フラグ希釈で実効5日以下、trip 単位の cd_only service |

## 全国走査 (gtfs-data.jp、current 世代の calendar 構造)

方法: 全 47 都道府県の /feeds を列挙 (重複除去) → current 世代 zip を取得 →
分類器適用。結果: data/daytype_survey/ (1フィード1 JSON + _summary.json)。
zip は保持しない (calendar 統計のみ記録。再取得は API で可能)。

(実行中 — 結果は本ドキュメントに追記)

## 海外候補 (追加検討)

- 取得済み: LA Metro (上表)。出典: gitlab.com/LACMTA/gtfs_bus (公開)
- 候補 (未取得): TfNSW シドニー (学期/休暇カレンダー。API キー要)、
  ドバイ RTA (ラマダンダイヤ。アカウント要)、ski リゾート系 (季節運行)。
  必要になった類型から順に。世代ペアが要る場合は Wayback (I1 と同じ手順)

## 次の使い方

1. 走査結果からタグ別に日本の代表フィードを選定 (小規模・ライセンス CC 系優先)
2. 選定フィードは gtfs-data.jp の世代 API (prev_N) でペアを即入手できる —
   Wayback 不要なのが国内の強み
3. 原則A/B の設計案を各類型に机上適用 → 反例探し → service_days.md v0.8 へ
