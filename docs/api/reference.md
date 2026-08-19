# リファレンス — CLI / Web API / JSON スキーマ

正確な仕様の定義。導入と使い方の案内は [README.md](README.md)。
設計の経緯は docs/design/ (architecture.md, ontology.md, ai_interface.md)。

## 1. CLI

インストール後のコマンドは `gtfs-semantic-diff`。共通オプション:
`--config <toml>` (閾値等の上書き。既定は config/default.toml)、`-v` (詳細ログ)。

### compare — 2世代の比較 (中心コマンド)

```
gtfs-semantic-diff compare [OLD.zip NEW.zip] [オプション]
```

入力はローカル zip 2つ (**古い方が先**) か、gtfs-data.jp 指定:

| オプション | 意味 |
|---|---|
| `--org` / `--feed` | gtfs-data.jp の組織 ID / フィード ID |
| `--old` / `--new` | 世代 RID (既定: prev_1 → current) |
| `-o FILE` | ChangeEventSet JSON (events.json) を書き出す |
| `--rawdiffs FILE` | RawDiff 全件 JSON を書き出す |
| `--report FILE` | Markdown レポート |
| `--html FILE` | 自己完結 HTML (全量同梱、ローカル閲覧向け) |
| `--html-lite FILE` | 軽量 HTML (Web と同じ core バンドル) |
| `--html-dir DIR` | アプリ+データ分割出力 (http 配信向け) |
| `--digest FILE.md` | AI 向けダイジェスト Markdown (L0。§7) |
| `--digest-json FILE.json` | 同 JSON |
| `--digest-route <ページ名>` | ダイジェストを1路線の詳細 (L1) に切り替える |
| `--digest-routes FILE.json` | 全路線の L1 を束ねた routes.digest.json (§7) |
| `--mapping FILE.json` | ID 対応表 mapping.json (§8) |

### fetch — 世代の取得確認

```
gtfs-semantic-diff fetch --org <org> --feed <feed> [--old prev_1 --new current] [--force]
```

gtfs-data.jp から2世代の zip を取得・キャッシュし、読み込めることと
規模 (routes/stops/trips 数) を表で確認する。

### identity — 同定結果のダンプ (デバッグ用)

世代間同定 (停留所クラスタ・route family・パターン対応) の中間結果を出す。
スキーマは安定インタフェースではない。

## 2. Web API (https://diff.gtfs.jp/)

### ジョブ

```
POST /api/jobs
Content-Type: application/json
{"type": "gtfs_data_jp", "org": "<org>", "feed": "<feed>",
 "old_uid": "<full-uuid>", "new_uid": "<full-uuid>"}
→ {"job_id": "<pair>", "status_url": "/api/jobs/<pair>"}
```

- uid は gtfs-data.jp の世代のフル UUID (`gtfs_file_uid`)。短縮形は不可。
- uid の代わりに `"old_rid": "prev_1", "new_rid": "current"` でも可
  (サーバーで uid に解決。rid は世代進行でずれるため URL の正準キーには uid を使う)。
- `GET /api/jobs/{pair}` → `{"status": "running" | "succeeded" | "failed", ...}`
- pair ID の形式: `{org}__{feed}__{old_uid先頭8桁}__{new_uid先頭8桁}`
- zip アップロード由来の比較は `POST /api/uploads` (Web UI が使う経路)。

### フィード探索 (gtfs-data.jp プロキシ)

```
GET /api/gtfs/feeds?pref=<県id> | ?org=<org>   # フィード一覧
GET /api/gtfs/files?org=<org>&feed=<feed>      # 世代一覧 (uid・有効期間)
```

上流 API は https://api.gtfs-data.jp/v2 (直接叩いてもよい)。

### 成果物の URL 体系 (版付き・不変)

| URL | 中身 |
|---|---|
| `/r/{pair}.html` | レポート入口 (常に最新版へ) |
| `/r/{pair}.digest.md` / `.digest.json` / `.routes.digest.json` / `.mapping.json` | **最新版エイリアス** (.html を差し替えるだけ) |
| `/r/{pair}/index.json` | 版台帳 (どの版があるか、latest) |
| `/r/{pair}/v/{版}.html` | 特定版のレポート |
| `/r/{pair}/v/{版}.json` | ビューア用データ (bundle。安定 IF ではない) |
| `/r/{pair}/v/{版}.events.json` | ChangeEventSet 全件 (gzip 配信) |
| `/r/{pair}/v/{版}.rawdiffs.json` | 生差分全件 (gzip 配信) |
| `/r/{pair}/v/{版}.digest.md` | AI 向けダイジェスト Markdown (L0。§7) |
| `/r/{pair}/v/{版}.digest.json` | 同 JSON |
| `/r/{pair}/v/{版}.routes.digest.json` | 全路線の L1 詳細 (gzip 配信。§7) |
| `/r/{pair}/v/{版}.mapping.json` | ID 対応表 (gzip 配信。§8) |
| `/feeds/{org}__{feed}.json` | フィード台帳 (計算済みペア一覧・経年の入口) |

版は生成したツールの CalVer (例: 2026.8.19.1)。一度書かれた版は不変。
注: 2026.7.30.2〜2026.7.30.5 は版名の日付が誤記 (実際の生成日は
2026-08-19)。版は不変のため改名せず、順序トークンとしては正しく並ぶ。
ツール更新後の初アクセスで新しい版が lazy に追加される。
digest は 2026.7.30.2 以降に生成された版に並置される (それ以前の版にはない)。
発見導線: レポート HTML の `<head>` に digest への `link rel="alternate"`、
サイトルートに機械向け案内 `/llms.txt`、本ドキュメントは `/docs/` で配信。
**index.json の versions[].artifacts が全成果物のマニフェスト**
(成果物名 → url・gzip・schema) — URL 規則の暗記は不要。
routes.digest / mapping / フィード台帳 / artifacts / CORS は 2026.7.30.4 以降の版から。
成果物 GET には CORS (全オリジン許可) が付き、ブラウザアプリから直接 fetch できる。

### 認証・制限

閲覧と上記 GET は認証不要。`/api/me/*` (履歴・保存 zip) は Google ログイン。
ジョブ投入には計算コストのガードがあり、超過時は拒否される。
大量の機械的投入はせず、まとまった処理は CLI をローカルで使うこと。

## 3. events.json (ChangeEventSet) — 安定インタフェース

トップレベル:

```jsonc
{
  "schema_version": 1,
  "feed": {              // 来歴。API 由来なら org_id/feed_id/uid/rid が入る
    "org_id": "", "feed_id": "", "old_uid": "", "new_uid": "",
    "old_rid": "", "new_rid": "",
    "old_source": "old.zip", "new_source": "new.zip",   // ローカル zip 由来
    "old_period": ["", ""], "new_period": ["", ""]
  },
  "generated_at": "...",
  "config_snapshot": { /* 使用した閾値 */ },
  "events": [ /* ChangeEvent の配列 */ ],
  "accounting": {
    "rawdiff_total": 5944,        // 生差分の全件数
    "explained": 5941,            // いずれかのイベントの証拠になった件数
    "explained_ratio": 0.9995,    // 被覆率 (説明台帳)
    "residual_breakdown_by_file": { /* 残差の所在 */ }
  },
  "context": { /* 補助情報 */ }
}
```

ChangeEvent:

```jsonc
{
  "event_id": "evt_000001",
  "type": "STOP_ADDED",             // 型 ID (下のカタログ。安定)
  "subject": {                       // 何についてのイベントか (名前ベース)
    "stop_cluster": "上土方落合", "name": "上土方落合"
    // 路線イベントなら route_family / route_group 等
  },
  "old_ref": null,                   // 旧世代側の参照 (ID を含む)
  "new_ref": { "cluster_id": "上土方落合#0", "platform_ids": ["215_01"] },
  "quantification": { /* 数値 (便数・日数・率など型ごと) */ },
  "evidence": ["rawdiff_005913"],   // 根拠の生差分 ID (rawdiffs.json に対応)
  "confidence": 1.0,
  "severity": "major" | "minor" | "info",
  "display_name_ja": "停留所新設",
  "display_name_en": "Stop added",
  "narrative_hints": { /* 文章化の補助 (任意) */ }
}
```

読み方の原則: **名前は subject、ID は old_ref/new_ref、数値は
quantification、根拠は evidence**。文章を作るとき数値を再計算しない。

## 4. イベント型カタログ (44種)

定義の正は docs/design/ontology.md (v0.2.4) と
src/gtfs_semantic_diff/model/event_types.py。severity は既定値
(個別イベントで上書きされ得る)。

### A. 路線の存在・同一性 (8)

| type | 意味 | severity |
|---|---|---|
| ROUTE_ADDED | 路線新設 | major |
| ROUTE_DISCONTINUED | 路線廃止 | major |
| ROUTE_RENAMED | 路線名変更 | minor |
| ROUTE_SPLIT | 路線分割 | major |
| ROUTE_MERGED | 路線統合 | major |
| ROUTE_RESTRUCTURED | 路線再編 | major |
| THROUGH_SERVICE_INTRODUCED | 直通運転開始 | major |
| THROUGH_SERVICE_DISCONTINUED | 直通運転終了 | major |

### B. 経路・停車パターン (8)

| type | 意味 | severity |
|---|---|---|
| PATTERN_EXTENDED | 運行区間延長 | major |
| PATTERN_TRUNCATED | 運行区間短縮 | major |
| STOP_INSERTED_IN_PATTERN | 経由停留所追加 | minor |
| STOP_REMOVED_FROM_PATTERN | 経由停留所削除 | minor |
| DETOUR_ADDED | 経由地追加 | minor |
| DETOUR_REMOVED | 経由地解消 | minor |
| TIME_BAND_VARIANT | 時間帯限定経路の変更 | minor |
| SHAPE_CHANGED | 経路形状変更 | minor |

### C. 便数・時刻 (8)

| type | 意味 | severity |
|---|---|---|
| SERVICE_DAYS_CHANGED | 運行日の変更 | minor |
| SERVICE_REDUCED | 減便 | minor |
| SERVICE_INCREASED | 増便 | minor |
| TRIPS_TRUNCATED | 一部便の区間短縮 | major |
| FIRST_LAST_CHANGED | 始発・終発時刻変更 | major |
| TIMETABLE_SHIFTED | 時刻一斉シフト | info |
| TRAVEL_TIME_CHANGED | 所要時間変更 | minor |
| DWELL_TIME_CHANGED | 停車時分変更 | info |

### D. 停留所・乗り場 (7)

| type | 意味 | severity |
|---|---|---|
| STOP_ADDED | 停留所新設 | major |
| STOP_REMOVED | 停留所廃止 | major |
| STOP_RENAMED | 停留所改称 | minor |
| STOP_RELOCATED | 停留所移設 | minor |
| PLATFORM_CHANGED | 乗り場変更 | minor |
| PLATFORM_ADDED | 乗り場新設 | info |
| PLATFORM_REMOVED | 乗り場廃止 | info |

### E. 運行日・カレンダー構造 (4)

| type | 意味 | severity |
|---|---|---|
| GENERATION_SCOPE | 同梱世代と比較範囲 | info |
| DAYTYPE_RESTRUCTURED | 曜日ダイヤ区分再編 | major |
| HOLIDAY_EXCEPTION_CHANGED | 祝日・特日運行の変更 | info |
| SEASONAL_SERVICE_CHANGED | 期間限定運行の変更 | minor |

### F. その他・メタ・残差 (9)

| type | 意味 | severity |
|---|---|---|
| DEMAND_RESPONSIVE_CHANGE | デマンド運行への移行兆候 | major |
| FARE_CHANGED | 運賃改定 | major |
| FEED_VALIDITY_CHANGED | フィード有効期間更新 | info |
| AGENCY_INFO_CHANGED | 事業者情報変更 | info |
| TRANSLATION_CHANGED | 翻訳データ変更 | info |
| ACCESSIBILITY_CHANGED | バリアフリー情報変更 | minor |
| HEADSIGN_CHANGED | 行先表示変更 | info |
| TECHNICAL_ID_CHURN | ID 張り替え (意味変化なし) | info |
| UNEXPLAINED_RESIDUAL | 未説明の残差 | info |

エラーチェックで特に見るのは **UNEXPLAINED_RESIDUAL** (システムが説明
できなかった差分 — データの異常か、ツールの未実装領域) と
**TECHNICAL_ID_CHURN** (内容が同一なのに ID だけ張り替わっている —
無害だが作成工程の癖が出る)。

## 5. rawdiffs.json

L0 の生差分全件。`{"rawdiffs": [{...}]}`。各要素:

```jsonc
{
  "rawdiff_id": "rawdiff_005913",  // イベントの evidence から参照される
  "file": "stops.txt",
  "kind": "row_added",             // row_added/row_removed/field_changed/column系 ほか
  "key": ["215_01"],               // 行を同定する主キー値列
  "column": "stop_name",           // field_changed 等のとき対象カラム
  "old_value": "旧値", "new_value": "新値"
}
```

行差分が閾値 (10万行) を超えたファイルは集約 RawDiff 1件に畳まれる
(削除/追加/変更の件数は保持)。

## 6. bundle (ビューア用データ) — 安定インタフェースではない

`/r/{pair}/v/{版}.json` はビューア (同版の HTML) 専用。schema_version を
持つが、ビューアと同時にしか更新されない前提の内部形式。プログラム・AI は
events.json / rawdiffs.json / digest を使うこと。

## 7. digest (AI 向け要約層、digest_schema 1)

CLI `--digest` (Markdown) / `--digest-json` (JSON)。同じ素材から生成され、
**便数・件数は人間向けレポートと一致する** (数値一致不変条件)。
設計: docs/design/ai_interface.md。

### L0 (フィード全体、`scope: "feed"`)

Markdown の見出し構造は固定 (スキーマの一部):
`# 差分ダイジェスト` → `## 1. 比較の概要` / `## 2. 全体集計` /
`## 3. イベント種別` / `## 4. 停留所の変化` / `## 5. 路線別の変化`
(路線ごとに `###`) / `## 6. 路線に紐付かない変化` / `## 7. 検証 (説明台帳)`。
ID は含まない (名前と数値のみ)。Markdown は変化のある路線を
`digest_routes_max` (config、既定200) 件まで載せ、超過は件数を明示して
JSON 版へ誘導する。

JSON のトップキー:

```jsonc
{
  "digest_schema": 1, "scope": "feed",
  "meta": { /* tool/version/generated_at/feed (uid等)/agency_names */ },
  "data": { "old": {...}, "new": {...}, "comparison_scope": ...,
            "service_days_note": ... },
  "totals": { "trips_by_day": [...], "pages": N, "pages_changed": N,
              "accounting": {...}, "lev1_trip_ratio": ... },
  "events_by_type": [{"type","name_ja","category","count"}],
  "stop_changes": { "renamed": [{"old","new","routes"}], "added": [...],
                    "removed": [...], "relocated": [...] },
  "routes": [{"name", "day_totals", "changes", "former_names"?}],
  "routes_unchanged": N,
  "non_route": { "meta_events": [...], "others": [...] },
  "verification": { /* accounting + technical_id_churn +
                       unexplained_residual + self_check */ }
}
```

`routes[].changes` の kind 語彙 (人間向けの一言ダイジェストと共通):
`route_added` / `route_removed` / `systems` / `reroute` / `trips` /
`retime` / `retime_minor` / `notes_only`。

### L1 (1路線の詳細、`scope: "route"`、`--digest-route <ページ名>`)

変化のある便は1便1レコード (`status` = added / removed / retimed /
rerouted、新旧の始発時刻、**trip_id 旧新**、変化した停留所数、rerouted は
停車追加/削除数)。無変化・ID のみ変更の便は件数に畳む。
`stop_pattern_changes` に停車列の変化 (追加/取りやめ停留所と影響便数)、
`time_bands` に③相当の時間帯別本数 (時間帯ビン × [旧,新]、方向・曜日別)、
`route_ids` に構成 family の route_id 旧/新リスト (軽注記) を含む。
時刻の全量マトリクスは含まない — 全量が要る場合は events.json /
rawdiffs.json へ。

### 全路線版 (`scope: "routes"`、`--digest-routes` / `v/{版}.routes.digest.json`)

L1 を route_group 名キーの1オブジェクトに束ねたもの:
`{"digest_schema": 1, "scope": "routes", "meta": {...}, "routes": {"<ページ名>": <L1>}}`。
Web 配信は gzip。

## 8. mapping.json (ID 対応表、mapping_schema 1)

CLI `--mapping` / Web `v/{版}.mapping.json` (gzip。**2026.7.30.5 以降の版を使うこと** — .4 は仮説エッジ混入の既知不具合)。identity 層
(内容主導・決定的な新旧同定) の直列化で、**世代を跨いだ ID の結合キー**を
提供する — 乗客データの経年分析、shapes 等整備資産の世代引き継ぎ、
設定移行のバックエンド。

```jsonc
{
  "mapping_schema": 1,
  "meta": { "feed": {...}, "tool_version": "..." },
  "counts": { "stops": N, "routes": N, "trips": N, "trips_by_relation": {...} },
  "stops": [{
    "relation": "renamed",            // continued/renamed/added/removed
    "old": {"name": "市役所前",  "stop_ids": ["S2"]},   // GTFS stop_id 群 (乗り場単位)
    "new": {"name": "表町一丁目", "stop_ids": ["S2"]},
    "confidence": 1.0, "method": "name_exact",
    "moved_m": 12,                    // 代表点の移動距離 (m、動いたときのみ)
    "events": ["evt_000003"]          // 関連 ChangeEvent (説明台帳への入口)
  }],
  "routes": [{
    "relation": "merged",             // continued/renamed/merged/split/restructured/added/removed
    "old": [{"name": "…", "route_ids": ["11","12"]}],   // N:M は配列のまま
    "new": [{"name": "…", "route_ids": ["W1"]}],
    "similarity": 0.82, "events": ["evt_000045"]
  }],
  "trips": [{ "relation": "id_churn", "old": "旧trip_id", "new": "新trip_id" }],
  "day_types": [{ "old": "weekday", "new": "weekday", "confidence": 1.0 }]
}
```

利用上の契約:

- **N:M は 1:1 に潰していない**。統合・分割は配列の対応として渡すので、
  結合時の按分などの判断は利用側で行うこと。
- **同一視の最終判断は利用側にある**。moved_m・renamed・relation は事実の
  提示であり、「移設120mを同一停留所と扱うか」は用途で決めること。
- **ツール版が上がると対応結果は変わり得る** (identity アルゴリズムの改良)。
  mapping は版付き・不変の成果物なので、パイプラインは版をピンして再現できる。
  最新版エイリアス (`/r/{pair}.mapping.json`) は追従用。
