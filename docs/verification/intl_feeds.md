# I1: 国際検証データセット台帳 (2026-07-13)

設計: docs/design/i18n.md I1。取得: `scripts/fetch_intl_feeds.py` (URL・版を恒久固定)、
実行記録: `scripts/probe_intl_feeds.py` → data/intl/results.json。
**zip は再配布しない** (data/ は gitignore)。このドキュメント + スクリプトが再現手段。

## 選定 (6フィード・特徴マトリクス)

| id | 都市/国 | 選定理由 | 世代ペア | 入手元 |
|---|---|---|---|---|
| trimet | ポートランド (米) | **歴史枠** (GTFS 発祥の地)・模範実装 | 2025-12-04 → 2026-06-03 | Wayback (developer.trimet.org) |
| mbta | ボストン (米) | **歴史枠**・多モード (地下鉄/CR/フェリー)・**Fares v2**・block_id | Winter 2026 (2025-11-27) → Summer 2026 (2026-05-27) | 公式アーカイブ (cdn.mbta.com/archive) |
| stm | モントリオール (加) | **歴史枠**・仏語 (非 ASCII・アクセント) | 2025-06-13 → 2026-06-03 | Wayback (stm.info) |
| rome | ローマ (伊) | **frequencies.txt** (ヘッドウェイ運行) の代表格・伊語 | 2025-04-06 → 2025-10-14 | Wayback (romamobilita.it) |
| swiss | スイス全国 | 国家規模 (中)・多モード鉄道・agency 多数 | FP2026 2025-12-20 → 2026-06-06 | 公式 (opentransportdata.swiss、年度データセット内の日付版) |
| ovapi_nl | オランダ全国 | **calendar_dates 主体**の運行日表現・国家規模 (大) = ストレステスト | 2026-01-01 → 2026-07-11 | 公式 (gtfs.ovapi.nl、archive/ + 最新) |

補欠・見送り: HSL ヘルシンキ (Wayback にスナップショットなし)、メキシコシティ
(過去版の公開入手手段なし)、transitfeeds.com (403 でスクリプト取得不可)。
frequencies は rome が担う。

## ライセンス (再確認前提のメモ)

| id | ライセンス (取得時点の理解) | 確認先 |
|---|---|---|
| trimet | TriMet Developer License (出典表記・自由利用) | developer.trimet.org/terms_of_use.shtml |
| mbta | MassDOT/MBTA Developers License | mbta.com/developers |
| stm | STM オープンデータ利用条件 (**要確認**: CC 系か独自か) | stm.info/en/about/developers |
| rome | Roma Mobilità オープンデータ (**要確認**: CC BY / IODL) | romamobilita.it/it/tecnologie/open-data |
| swiss | Open data (出典表記。opentransportdata.swiss 利用規約) | opentransportdata.swiss/en/terms-of-use |
| ovapi_nl | NDOV/OVapi 公開データ (**要確認**: CC0 相当か) | ovapi.nl |

方針: 検証は「アップロード相当のローカル利用」なので取得時点で問題なし。
**公開レポート化・観測所掲載など二次利用を広げる場合は、この表の要確認を
解消してから** (i18n.md I5 の前提)。

## 実行記録 (probe_intl_feeds.py、ローカル Mac)

> 記入待ち: data/intl/results.json から転記

## 課題一覧 (I3/I4 への入力)

> 記入待ち
