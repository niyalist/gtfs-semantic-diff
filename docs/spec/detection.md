# 変化検出仕様書 (実装準拠・v0.2.1)

本書は gtfs-semantic-diff が **どういう変更を、どういうロジックで認識するか** の網羅的な仕様である。
設計時のイベントカタログは [../design/ontology.md](../design/ontology.md)、モジュール構成は
[../design/architecture.md](../design/architecture.md) を参照。本書は**実装済みの挙動**を正とし、
コード (src/gtfs_semantic_diff/) と食い違う場合はバグとして扱う。

閾値・重みはすべて `config/default.toml` にあり、本文中では `[セクション] キー` で参照する。

```
GtfsSnapshot ×2
  → L0: RawDiff 全列挙 (§1)
  → L1: 世代間同定 MatchGraph (§2)
  → trip 照合 (§3)
  → L2: ルールカスケード → ChangeEvent (§4)
  → 説明会計: 未消費 RawDiff → UNEXPLAINED_RESIDUAL (§5)
```

---

## 0. 前提: 読み込み時の正規化

- zip 内の **全 `.txt`** を読む (既知ファイル限定にしない。未知ファイルの差分も L0 に現れる)。
- 全列を文字列として読み、欠損は空文字列 `""` に統一する。値の比較はすべて生文字列比較。
- 文字コードは UTF-8 (BOM 可) → cp932 の順で試行。zip 直下に `.txt` がない場合は 1 階層下を探す。
- calendar / calendar_dates から service_id ごとの **day_type** を正規化する:

| day_type | 判定条件 |
|---|---|
| `weekday` | calendar の月〜金 = 1 かつ 土日 = 0 |
| `saturday` / `sunday_holiday` | 土のみ / 日のみ |
| `weekend` | 土日のみ |
| `daily` | 全曜日 |
| `irregular` | 上記いずれにも該当しない |

calendar に現れない (または全フラグ 0 の) service は calendar_dates の追加運行日
(exception_type=1) で判定する。運行日数が `[load.day_types] short_service_max_days`
(10) 以下なら曜日分布に関わらず `irregular` (年末年始・お盆等の短期間専用ダイヤが
平日等の時刻表に混入するのを防ぐ — 永井運輸の実例から採録)。それ以外は曜日分布の
多数決: `calendar_dates_majority` (0.8) 以上が単一区分 (平日/土/日) に収まれば
その区分、収まらなければ `irregular`。
国民の祝日カレンダーは参照しない (祝日が平日に落ちる場合の誤差は許容)。

---

## 1. L0: RawDiff 全列挙 (diff0/engine.py)

説明会計の**分母**。2 世代間の機械的差分を決定的順序で全列挙し、`rawdiff_NNNNNN` の
連番 ID を振る (同一入力 → 同一 ID)。粒度の規約:

| 状況 | 生成される RawDiff |
|---|---|
| ファイルが片側にのみ存在 | `file_added` / `file_removed` **各1件** (中の行は列挙しない) |
| カラムが片側にのみ存在 | `column_added` / `column_removed` (カラムごとに1件。行の値は列挙しない) |
| 行が片側にのみ存在 (主キー突合) | `row_added` / `row_removed` |
| 両側にある行の値の相違 | `field_changed` (**セル単位**。共通カラムのみ比較) |

行の同定は主キーによる。主キー定義 (`KEY_COLUMNS`):

| ファイル | 主キー |
|---|---|
| agency, agency_jp | agency_id |
| stops | stop_id |
| routes, routes_jp | route_id |
| trips | trip_id |
| stop_times | (trip_id, stop_sequence) |
| calendar | service_id |
| calendar_dates | (service_id, date) |
| fare_attributes | fare_id |
| fare_rules | (fare_id, route_id, origin_id, destination_id, contains_id) のうち存在するカラム |
| shapes | (shape_id, shape_pt_sequence) |
| frequencies | (trip_id, start_time) |
| transfers | (from_stop_id, to_stop_id) |
| feed_info | 単一行ファイルとして全フィールド比較 |
| translations | (table_name, field_name, language, record_id, record_sub_id, field_value) |
| office_jp / levels / pathways / attributions / booking_rules / location_groups | 各 *_id |

**フォールバック**: 主キーが未定義のファイル、主キーカラムが欠落・重複しているファイルは、
行全体の多重集合比較に切り替える (変更は `row_removed` + `row_added` の対として現れる。
キーは行内容の SHA-1 ダイジェスト + 出現番号、行内容自体を old_value / new_value に保持)。

---

## 2. L1: 世代間同定 (identity/)

ID の連続性を仮定せず「同じもの」を再構成する。結果は MatchGraph
(old ↔ new, confidence 0–1, method) のエッジ集合。**仮説は破棄せず保持**し、
採否は L2 側が `[events] accept_confidence` (0.5) で判断する。

### 2.1 停留所クラスタ (2段階)

**段階1 (世代内名寄せ)** — プラットフォーム (stop_id) を物理停留所にまとめる:
1. `location_type=1` の parent_station があればそのクラスタに所属。
2. なければ **基底名** (stop_name から「のりば・乗り場・番線・末尾の数字/丸数字/A-F」を
   反復除去した名称) が同じで、既存クラスタ代表座標から
   `[identity.stop_clustering] intra_generation_radius_m` (100m) 以内なら同一クラスタ。
3. どちらも満たさなければ新クラスタ。処理順は stop_id 昇順 (決定的)。

**段階2 (世代間リンク)** — クラスタ対のスコアリング:

```
score = 0.35 × プラットフォーム共有率 (共有 stop_id 数 / max(旧,新))
      + 0.25 × 接続 route family 集合の Jaccard   ← route_id でなく family 名で比較
      + 0.25 × 距離スコア (1 − d / inter_generation_radius_m)
      + 0.15 × 基底名の文字列類似度 (SequenceMatcher)
```

- 候補は空間グリッド (セル幅 ≈ 300m) の近傍 3×3 に加え、**stop_id を共有するクラスタは
  距離に関係なく候補に含める** (300m 超の移設でも stop_id が同じなら同定できる)。
- `link_floor` (0.25) 以上のエッジを全て保持。基底名完全一致は method=`name_exact`、
  それ以外は `composite`。

### 2.2 Route Family

- family = 利用者が認識する「路線」。**route_short_name → route_long_name → route_id**
  の優先順で表示名を取り、完全一致でグループ化 (正規化・あいまい一致はしない)。
- 世代間リンク: 名称一致 → confidence 1.0 (`name_exact`)。
  名称不一致の family 同士は、所属する停車パターン集合 (基底名列のダイジェスト集合) の
  Jaccard が `[identity.route_family] link_floor` (0.3) 以上なら仮説エッジ
  (`pattern_jaccard`) として保持 → ROUTE_RENAMED の判定材料。

### 2.3 停車パターンクラスタ

- パターン = (family, direction_id) 内の一意な**停留所クラスタ基底名列**。
  stop_id でなく基底名列で表すことで、ID が全交換されても世代間比較が成立する。
- パターン間類似度:

```
sim = 0.6 × LCS類似 (2·LCS長 / (len_a + len_b))
    + 0.3 × 順序整合 (共通停留所の相対順序が保存されるペアの割合。共通2未満は 0.5)
    + 0.1 × 包含 (一方の停留所集合が他方の部分集合なら min_len / max_len、それ以外 0)
```

- 世代内クラスタリング: `similarity_threshold` (0.5) 以上を辺とする連結成分。
  パターン数が `hierarchical_switch_patterns` (50) を超える family×方向は
  (始点, 終点, 長さ÷5) で予備グループ化してから成分分解 (O(n²) 回避)。
- 世代間リンク: 対応 family ペア内で代表パターン同士の sim × family信頼度 が
  `link_floor` (0.3) 以上のエッジを保持。

### 2.4 service (運行日種別)

新旧両世代に存在する day_type 同士を confidence 1.0 で対応付ける (method=`day_type`)。

### 2.5 route_group (路線ブランド、identity/route_group.py)

family の上の集約層。枝番系統 (30A/30B/… 前橋玉村線) を利用者が認識する
「路線」に束ねる (設計と実測根拠: docs/design/route_group.md、M6 調査)。

- **グループ化キー = 語幹**: NFKC 正規化した family 表示名から、先頭の系統コード
  らしき連続 (英数字・空白・ハイフン類・中点・記号) を除去したもの。
- ガード: 語幹が `[identity.route_group] min_stem_len` (2) 未満、または
  `stem_stopwords` (系統・線・循環・バス) に該当する場合はグループ化しない
  (正規化済み元名を語幹とする)。全 family が必ずいずれかの group に所属する。
- **停留所集合 Jaccard はゲートに使わない** (枝番系統は同一ブランド下の別コリドーが
  普通なため)。group の凝集度 (構成 family 対の median Jaccard) として算出し、
  `low_cohesion_note` (0.2) 未満ならレポートが「枝線構造」と注記する。
- 出力: 全 A/B/C 群イベントの subject に `route_group` を付与 (新世代の対応優先)。
  JSON の `context.route_groups` (構成と凝集度) / `context.family_structure`
  (family 内の運行系統構成 — 停車地がほぼ重ならないクラスタの同居を列挙、
  レポートの小見出し分割に使用) / `context.band_profiles` の `route_group` 列。
- GTFS-JP 固有フィールド (jp_parent_route_id 等) は使わない (CLAUDE.md 開発ルール)。

---

## 3. trip 照合 (events/tripdelta.py — trip matching v2)

**trip_id の連続性は一切仮定しない。ID の一致は同一性の定義ではなく証拠の一つ
(弱い事前) として扱う** — 連番型 ID 運用 (八戸型) では便の増減で同じ ID が
別の時刻の便を指すため (設計: docs/design/trip_matching.md、根本原因:
docs/verification/trip_identity_survey.md)。

手順:
1. 内容署名 `(family, direction, day_type, 停車クラスタ基底名列, 全停留所の
   発着時刻列)` の**完全一致** → exact (同一 trip_id を優先ペアリング)
2. 残りを **(route_group, day_type) のブロック内でコスト最小割当** (枝番 route 間の便移動に対応。2026-07-09 改訂):
   `cost = min(Δt_shared, cap)/cap + w_route·(1−LCS率) − w_id·[同一ID]`
   - **Δt_shared = 共有停留所での発時刻差の中央値** (区間短縮・延長に頑健)
   - 受理ゲート: LCS率 ≥ `[matching] min_route_sim` かつ Δt_shared ≤ `max_shift_min`
   - コスト昇順の決定的貪欲 (感度分析で正解/非正解コストは大きく二極化:
     正解 p95 = 0.1 vs 非正解 p5 = 0.77)
3. 残り → removed / added

| 分類 | 条件 | 主な用途 |
|---|---|---|
| exact | 署名完全一致の新旧ペア | ID も同一なら「変更なし」 |
| churn | exact のうち trip_id が異なる対 | TECHNICAL_ID_CHURN |
| modified | ブロック内割当で対応した対 (**ID は跨ぎうる**) | 時刻修正 (C群)・経路変更 (B群) |
| removed / added | ゲートを満たす相手が無い | 便数増減 (C群)、路線廃止・新設 (A群) |

既知の制限 (v1): family 対応が無い・day_type が変わった便はブロックを跨げず
removed+added になる (クリーン正解での recall 0.992、未回収3件はすべてこの制限)。

---

## 4. L2: イベント検出ルール (events/rules/)

カスケード順: **stops → routes → patterns → frequency → calendars → shapes → metadata
→ technical**。各イベントは検出と同時に evidence (説明する RawDiff の ID 集合) を
台帳に記録する (`RuleContext.emit` が不可分に行う)。複数イベントが同じ RawDiff を
参照してよいが、主説明 (primary) は先勝ちで 1 イベント。

**カスケード消費の規約**: 上位イベントは配下の差分を丸ごと説明する。
路線廃止 = routes 行 + 所属 trip の trips/stop_times 全行。経路変更 = その trip の
stop_times 差分全体 (経路が変われば下流時刻・headsign も連鎖して変わるため)。

### 4.1 D群: 停留所 (rules/stops.py)

| イベント | 検出条件 | evidence | severity |
|---|---|---|---|
| STOP_REMOVED | 旧クラスタの最良エッジ confidence < accept_confidence (0.5) | 構成 stop_id の stops.txt row_removed | major |
| STOP_ADDED | 新クラスタが同様に未対応 | row_added | major |
| STOP_RENAMED | 対応済みクラスタ対の共有 stop_id に stop_name の field_changed | 当該 field_changed | minor |
| STOP_RELOCATED | 対応済み対に stop_lat/lon の field_changed があり、代表座標の移動が `[events.stops] relocated_threshold_m` (300m) 超 | 当該 field_changed | minor |
| PLATFORM_CHANGED (座標) | 同上で移動が閾値以下 (乗り場位置の微修正) | 同上 | info |
| PLATFORM_CHANGED (付け替え) | stop_times の stop_id が field_changed で、新旧の stop_id が**世代間で対応するクラスタ**にそれぞれ属する (基底名一致 or MatchGraph エッジ) | 当該 stop_times field_changed | minor |
| PLATFORM_ADDED / REMOVED | 対応済みクラスタ内で stop_id 集合が増減 | stops.txt row_added / row_removed | info |
| ACCESSIBILITY_CHANGED | 共有 stop_id の wheelchair_boarding field_changed | 当該 field_changed | minor |

confidence はクラスタ対応エッジの confidence を伝播。

### 4.2 A群: 路線 (rules/routes.py)

判定順序が重要: **RENAMED → route_id churn → DISCONTINUED/ADDED** (名称変更を
「廃止+新設」と誤認しないため)。

| イベント | 検出条件 | evidence |
|---|---|---|
| ROUTE_RENAMED | 名称不一致 family 対の pattern_jaccard エッジが `[identity.route_family] pattern_jaccard_renamed` (0.7) 以上 | 新旧 route_id の routes.txt 行差分 |
| ROUTE_RENAMED (minor) | 名称一致 family 内で共通 route_id の route_short_name / route_long_name が field_changed | 当該 field_changed |
| TECHNICAL_ID_CHURN (route_id) | 名称一致 family 内で route_id 集合だけが変化 | routes.txt 行差分 + trips.txt の route_id field_changed |
| ROUTE_DISCONTINUED | family が消滅し RENAMED でも説明されない | routes 行 + **所属 trip の trips/stop_times 全行 (カスケード)** |
| ROUTE_ADDED | family の出現 (同上) | 同上 (row_added 側) |
| SEASONAL_SERVICE_CHANGED | 消滅/出現 family の全 trip が day_type=irregular (特定日運行のみ) の場合、DISCONTINUED/ADDED の代わりに発行。confidence 0.6 の仮説 | 同上 |

**未実装**: ROUTE_SPLIT / ROUTE_MERGED / THROUGH_SERVICE_INTRODUCED / _DISCONTINUED。

**既知の限界**: フィードが季節路線を通常の calendar (平日/土日祝) で記述している場合
(例: 地鉄ぶりかにバス)、データ単体では季節性を判定できず ROUTE_DISCONTINUED になる。

### 4.3 B群: 停車パターン (rules/patterns.py)

対象は **modified** trip (割当で対応した対。ID は跨ぎうる) のうち停車列 (基底名列) が変化したもの。
新旧列を difflib.SequenceMatcher の編集操作 (opcodes) に分解し、操作ごとに分類:

| 操作 | イベント |
|---|---|
| 端点への追加 (先頭/末尾) | PATTERN_EXTENDED (major) |
| 端点からの削除 | PATTERN_TRUNCATED (major) |
| 中間への挿入 1 停留所 | STOP_INSERTED_IN_PATTERN (minor) |
| 中間への挿入 連続 2+ | DETOUR_ADDED (minor) |
| 中間からの削除 1 / 連続 2+ | STOP_REMOVED_FROM_PATTERN / DETOUR_REMOVED (minor) |

同一の変化内容 (family × 方向 × day_type × 種別 × 停留所列) の trip はまとめて
1 イベント。evidence は**当該 trip の trips/stop_times 差分の全体** (時刻連鎖変更・
headsign を含む)。1 trip に複数の変化がある場合は複数イベントが同じ evidence を共有し、
最初のイベントが primary。

trip が丸ごと入れ替わる形のパターン変化は C群 (SERVICE_*) 側で会計される。
**未実装**: TIME_BAND_VARIANT。

### 4.4 C群: 便数・時刻 (rules/frequency.py)

比較単位は (family × direction × day_type)、時刻は各 trip の始発停留所の発時刻、
時間帯ビンは `[events.frequency] time_bands` (既定 5-7 / 7-9 / 9-16 / 16-19 / 19-22 /
22-29時、24時超え表記対応、どれにも入らなければ `other`)。
プールは removed / added のうち **A群が主消費済みでない trip** (廃止路線の便を減便と
二重計上しない)。

| イベント | 検出条件 | 備考 |
|---|---|---|
| SERVICE_REDUCED | ビンの本数 旧 > 新 | `major_bands` (7-9, 16-19時) では severity=major |
| SERVICE_INCREASED | ビンの本数 旧 < 新 | minor |
| TIMETABLE_SHIFTED (uniform=false) | ビン本数同数だが便の入れ替えあり (時刻変更) | info |
| FIRST_LAST_CHANGED | グループの始発 or 終発が `first_last_threshold_min` (15分) 超変化 | evidence は空 (該当便は当該ビンのイベントが主消費) |
| TIMETABLE_SHIFTED (uniform=true) | modified trip で全停留所の時刻差の標準偏差 ≤ `[events.timetable] uniform_shift_max_std_sec` (120秒) | 同一シフト量の trip をまとめる |
| TRAVEL_TIME_CHANGED | modified trip で時刻変化が非一様 | quantification に区間別 {segment, old/new_median_sec, old/new_p90} を \|中央値差\| 上位5区間まで保持 |

evidence: SERVICE_* / uniform=false は該当便の trips + stop_times 全行 (カスケード)。
uniform / TRAVEL_TIME は arrival_time / departure_time の field_changed。
**未実装**: DWELL_TIME_CHANGED、TRIPS_TRUNCATED (truncated パターンへの移動検出)。

### 4.5 E群: カレンダー (rules/calendars.py)

| イベント | 検出条件 |
|---|---|
| DAYTYPE_RESTRUCTURED | 世代間で day_type 集合が変化 (例: 土曜ダイヤの calendar_dates 化)。evidence は calendar.txt の行増減・曜日フラグ変更。confidence 0.8 |
| FEED_VALIDITY_CHANGED | calendar.txt の start_date / end_date の field_changed (期限の書き換え) |
| HOLIDAY_EXCEPTION_CHANGED | calendar_dates.txt の差分を service の day_type ごとに集約。**新旧有効期間の重なり窓で正規化**: 窓内の差分 = 実質的な運行例外変更 (`within_overlap`)、窓外 = フィード期間スライドの機械差 (`outside_overlap`)。quantification の `substantive` で区別。窓が求まれば confidence 1.0、不明なら 0.8 |

有効期間は API メタデータ (from_date/to_date) → calendar/calendar_dates の
最小・最大日付の順で解決する。

### 4.6 形状 (rules/shapes.py)

ポリラインは shape_pt_sequence 順、`[events.shape] max_polyline_points` (200) 点に間引き。
幾何比較は**離散 Fréchet 距離** (等長方形近似での平面距離)。

| イベント | 検出条件 |
|---|---|
| TECHNICAL_ID_CHURN (shape_id) | trips.txt の shape_id 付け替え対で、旧新ポリラインの Fréchet < `frechet_threshold_m` (150m) — 形は同じで ID だけ変更 |
| SHAPE_CHANGED (significant=true) | Fréchet ≥ 閾値 (実際の経路変形)、または片側にしか幾何がない | 
| SHAPE_CHANGED (significant=false) | 同一 shape_id に差分はあるが Fréchet < 閾値 (点列の振り直し・精度変更)。severity=info |

quantification: frechet_m, max_deviation_m (旧経路各点から新経路への最近距離の最大) と
その位置座標 max_deviation_at。停留所間区間への局在化は未実装 (最大乖離点で代替)。

### 4.7 F群: 運賃・運用形態・メタデータ (rules/metadata.py)

| イベント | 検出条件 / quantification |
|---|---|
| FARE_CHANGED | fare_attributes / fare_rules の全差分を 1 イベントで消費。新旧 fare_attributes の突合で removed_fares / added_fares (fare_id + price)、price_changes を分解 (各20件まで) |
| DEMAND_RESPONSIVE_CHANGE | 兆候の合成: (1) stop_times の pickup_type / drop_off_type が 2 (要電話) / 3 (要調整) との間で変化、(2) continuous_pickup / continuous_drop_off の変化、(3) booking_rules / location_groups / location_group_stops の出現、(4) frequencies.txt の変化。confidence = 0.5 + 0.15×(兆候数−1)、上限 0.9。兆候 2 個以上で severity=major |
| HEADSIGN_CHANGED | trip_headsign / stop_headsign の field_changed のうち**未消費分** (経路変更に伴う分は B群が消費済み)。family ごとに集約、変更例を samples に保持 |
| FEED_VALIDITY_CHANGED | feed_info.txt の全差分 |
| AGENCY_INFO_CHANGED | agency.txt / agency_jp.txt の全差分 |
| TRANSLATION_CHANGED | translations.txt の全差分 |

### 4.8 TECHNICAL_ID_CHURN (trip) (rules/technical.py)

trip 照合 (§3) の churn 対 (内容署名完全一致・trip_id 相違) を family × day_type 単位で
まとめ、当該 trip 対の trips / stop_times 全行差分のうち未消費分を消費する。
内容が完全一致しているため confidence 1.0 で「ダイヤ同一の ID 張り替え」と断定できる。
route_id / shape_id の churn はそれぞれ A群 / 形状ルールが扱う (§4.2, §4.6)。

---

## 5. 説明会計と残差

- `explained_ratio = (UNEXPLAINED_RESIDUAL 以外のイベントに説明された RawDiff 数) / 全 RawDiff 数`
- カスケード終了後、どのイベントの evidence にも入らなかった RawDiff をファイル単位の
  UNEXPLAINED_RESIDUAL イベントに集約する (残差イベントによる消費は「説明」に数えない)。
- レポートのデータ検証章に explained_ratio と残差全件を必ず表示する。
- **残差はルールカタログ育成の KPI**: 残差を精査し、既存ルールの穴 (例: 300m 超の移設)
  は修正、意味のある未知の変化 (例: 行先表示変更) は ontology への新タイプ採録で対応する。

## 6. 閾値・設定一覧 (config/default.toml)

| キー | 既定値 | 用途 (参照節) |
|---|--:|---|
| load.day_types.calendar_dates_majority | 0.8 | day_type 判定の曜日多数決 (§0) |
| load.day_types.short_service_max_days | 10 | 短期間サービスの特定日分類 (§0) |
| identity.stop_clustering.intra_generation_radius_m | 100 | 世代内名寄せ半径 (§2.1) |
| identity.stop_clustering.inter_generation_radius_m | 300 | 世代間リンク半径 (§2.1) |
| identity.stop_clustering.link_floor | 0.25 | リンク仮説保持下限 (§2.1) |
| identity.stop_clustering.weight_* | 0.35/0.25/0.25/0.15 | リンクスコア重み (§2.1) |
| identity.pattern_clustering.similarity_threshold | 0.5 | 同一クラスタ判定 (§2.3) |
| identity.pattern_clustering.lcs/direction/containment_weight | 0.6/0.3/0.1 | 類似度重み (§2.3) |
| identity.pattern_clustering.hierarchical_switch_patterns | 50 | 予備グループ化切替 (§2.3) |
| identity.pattern_clustering.link_floor | 0.3 | 世代間リンク下限 (§2.3) |
| matching.min_route_sim | 0.5 | trip 対応の受理に必要な停車列 LCS率 (§3) |
| matching.max_shift_min | 60 | trip 対応の受理に必要な Δt_shared 上限 (§3) |
| matching.time_cap_min / w_route / w_id | 60 / 1.0 / 0.05 | trip 対応コストの正規化・重み (§3) |
| identity.route_family.pattern_jaccard_renamed | 0.7 | ROUTE_RENAMED 確定 (§4.2) |
| identity.route_family.link_floor | 0.3 | RENAMED 仮説保持下限 (§2.2) |
| identity.route_group.min_stem_len | 2 | 語幹の最小長 (§2.5) |
| identity.route_group.stem_stopwords | 系統/線/循環/バス | 退化語幹ガード (§2.5) |
| identity.route_group.low_cohesion_note | 0.2 | 枝線構造注記・小見出し分割 (§2.5) |
| identity.route_group.structure_min_trips | 2 | 構成表示の最小便数 (§2.5) |
| events.accept_confidence | 0.5 | エッジ採用の下限 (§4) |
| events.frequency.time_bands | 6ビン | 時間帯ビン (§4.4) |
| events.frequency.major_bands | 7-9, 16-19時 | 減便 major 判定 (§4.4) |
| events.frequency.first_last_threshold_min | 15 | 始発終発の報告下限 (§4.4) |
| events.stops.relocated_threshold_m | 300 | 移設判定 (§4.1) |
| events.shape.frechet_threshold_m | 150 | 形状変化の有意判定 (§4.6) |
| events.shape.max_polyline_points | 200 | Fréchet 前の間引き (§4.6) |
| events.timetable.uniform_shift_max_std_sec | 120 | 一様シフト判定 (§4.4) |

## 7. 未実装・既知の限界 (まとめ)

- ROUTE_SPLIT / ROUTE_MERGED / THROUGH_SERVICE_* (A群)
- TIME_BAND_VARIANT (B群)、DWELL_TIME_CHANGED / TRIPS_TRUNCATED (C群)
- SHAPE_CHANGED の停留所間区間への局在化
- 祝日カレンダー非参照による day_type 判定誤差
- 通常 calendar で記述された季節路線の季節性判定 (多世代タイムライン分析が必要)
- 多世代 (N≥3) のイベント列連結・揺らぎ検出 (events/timeline.py, 将来)
