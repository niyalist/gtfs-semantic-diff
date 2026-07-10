# W3-2a 検証記録: uid 正準 URL と版管理 (2026-07-11)

設計: docs/design/web.md「W3-2 詳細方針」、決定の経緯: docs/design/w3_2_directions.md §7〜8。
実装: infra/runtime/versioning.py (純ロジック) + handler.py + viewer/VersionBar.svelte。

## 検証環境

- スタック: GtfsSemdiffDelivery (ap-northeast-1)、CloudFront d22mbbm5uatfcc.cloudfront.net
- ツール版: 2026.7.11.1 (CalVer YYYY.M.D.N)
- 検証ペア: 永井運輸 Nagaibus prev_2 (uid 4a4a81e7…) → prev_1 (uid b1be1add…)
  = 基準ペア (2025-10-01 改正)

## 確認項目と結果 (すべて 2026-07-11 実測)

| 項目 | 結果 |
|---|---|
| files API が uid を返す | ✓ `GET /api/gtfs/files` に uid 追加 |
| uid 指定投入 → 正準 job_id | ✓ `nagai-unyu__Nagaibus__4a4a81e7__b1be1add` |
| 初回生成 (queued→succeeded) | ✓ 約50秒 |
| 入口 `r/{pair}.html` | ✓ 200, cache-control: max-age=300 |
| 版固定 `r/{pair}/v/2026.7.11.1.html` | ✓ 200, max-age=31536000, immutable |
| `r/{pair}/index.json` (版台帳) | ✓ versions/latest/feed (uid・from_date) |
| 同一ペア再投入 = lazy キャッシュ | ✓ 0.26秒で即 succeeded (再計算なし) |
| 旧クライアント互換 (rid 指定) | ✓ prev_2/prev_1 → 同一 uid ペアに解決され即返し |
| レポート meta | ✓ old_uid/new_uid・feed_license "CC BY 4.0"・tool version 埋め込み |
| explained_ratio | ✓ 1.0 (永井基準ペアの回帰どおり) |

## 途中で直した不具合

- API Lambda に `r/*` の s3:GetObject 権限がなく、lazy 判定の index.json 読みが
  AccessDenied → 500。`bucket.grant_read(api_fn, "r/*")` を付与し、_get_index は
  読み取り失敗時に None (= 再計算する側) へ倒すよう堅牢化 (投入は失敗させない)。

## 未確認 (次の機会に自然に検証されるもの)

- **版が2つ以上あるときのビューア版バー表示** (新版案内・版セレクタ)。現時点で
  全ペア1版のためバーは非表示 (単版では出さない仕様どおり)。次のツール版
  (2026.7.11.2 以降) をデプロイして同一ペアを再投入すれば、旧版ページに
  「▲ より新しい解析版があります」、入口に版セレクタが出るはずである。
  次回デプロイ時に確認すること。
- アップロード由来 (r/anon/、ランダム URL・版管理なし) はコード変更が
  書き込みヘルパの抽出のみのため回帰確認は省略した。

## 運用メモ

- 旧 rid ベースの生成物 (`r/{org}__{feed}__{rid}__{rid}.html`) はそのまま残置
  (URL は生きるが以後更新されない。新キーとは衝突しない)。
- index.json の read-modify-write に排他なし: 同版の同時生成は同一内容の上書きで
  無害。異版競合はデプロイ直後の一瞬のみで、次回投入で自己修復する。
- ロールバック運用中に旧版で再生成しても latest は巻き戻らない
  (update_index が最大版を latest にする + 入口コピーは自版が latest のときのみ)。
