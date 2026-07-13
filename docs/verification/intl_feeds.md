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

## 実行記録 (probe_intl_feeds.py、ローカル Mac、2026-07-13)

P1 (便対応付け LCS メモ化、コミット 33ec2d1) 適用後。( ) 内は P1 前の値。
タイムアウトは 1800 秒/ペア。

| feed | 結果 | 合計 | diff0 / identity / 便対応 / ルール段 | RawDiff | イベント | explained | ピークRSS |
|---|---|---|---|---|---|---|---|
| trimet | ✓ | **273s** (旧 1789s) | 35 / 7 / 185 (旧1700) / 47 | 660万 | 4,535 | 0.9999 | 5.8GB |
| mbta | ✓ | **1677s** (旧 >1800 TO) | 71 / 15 / 294 (旧1356) / **1291** | 1172万 | 26,788 | 0.9958 | 7.7GB |
| stm | ✓ | 994s | 81 / 20 / 499 / 387 | 1449万 | 20,685 | **1.0000** | 9.8GB |
| rome | ✓ | 1523s | 114 / 20 / 386 / 996 | 1520万 | 11,015 | 0.9834 | 8.6GB |
| swiss | ▲ TO | >1800s | 475 / 115 / 727 完了 → ルール段で打ち切り | — | — | — | — |
| ovapi_nl | ▲ TO | >1800s | 410 / 70 完了 → 便対応の途中で打ち切り | — | — | — | — |

残差の内訳 (完走4件):

- trimet: stop_features.txt 321 (独自ファイル)、transfers 96、stops 29
- mbta: transfers 22,838、multi_route_trips 15,566、trips_properties 4,790、
  route_patterns 1,852、pathways 840 (独自+駅構内系)
- stm: stops 356、routes 218 — ほぼ完全
- rome: **stop_times 238,527・trips 13,748** (要精査 — frequencies 系?)

**所見**: (1) 都市規模4件は全て完走し、台帳 (explained_ratio) は 0.98〜1.0 —
検出の骨格は国際フィードでそのまま機能する。(2) P1 で便対応は 4.6〜9 倍改善したが、
**ルール段 (L2) が新たな支配項** (MBTA 1291s、rome 996s — RawDiff 1000万件超で
非線形の疑い)。(3) 国家規模2件は現状対象外の実測根拠が得られた。

## 課題一覧 (P2 / I3 / I4 への入力)

| # | 行き先 | 内容 |
|---|---|---|
| IN-1 | **P2 最優先** | ルール段 (L2) が RawDiff 大量時に非線形 (MBTA 1291s / rome 996s / trimet 47s)。プロファイルで特定して修正 |
| IN-2 | P2 | 便対応の残コスト (Δt 計算×候補対、タプルハッシュ)。swiss 727s / stm 499s。ブロック内前絞り等 |
| IN-3 | P2/I4 | shapes・stop_times 由来の巨大 RawDiff (660万〜1520万) — メモリ (RSS 10GB 級 = Lambda 不可) と HTML サイズに直結。bulk の適用拡大は evidence 設計と要調整。hosted bundle 化とも関連 |
| IN-4 | I4 | rome の残差 25万件 (stop_times/trips) の精査 — frequencies 運行の便の扱いを確認 |
| IN-5 | I4 | 未知ファイルの claiming ルール (MBTA multi_route_trips 等・TriMet stop_features) — 山交 pass_rules と同じバックログの国際版。transfers.txt (標準) のルールも未実装 |
| IN-6 | 方針 | 国家規模アグリゲート (swiss/NL) は当面 Web 対象外と明文化。per-agency 分割前処理は将来構想 |
| IN-7 | I4 (G5) | 地図タイルの国際化 (既知・最重要 UI 課題) |

HTML レポート: 各ペアの report.html を data/intl/{id}/ にローカル生成
(scripts 参照。TriMet 級は rawdiffs.json 埋め込みでファイルが巨大になる — IN-3)。
