# HTML バンドル生成のメモリ配管 — P2/IN-3 前半 (2026-07-24)

## 背景 (Lambda OOM の実測)

prt (ピッツバーグ) を Web 投入したところ **Runtime.OutOfMemory** (Max Memory
3007/3008MB、374秒) で失敗 (2026-07-23、CloudWatch)。ステージ別 RSS を実測すると:

- イベント生成まで (load 0.90 → diff0 1.75 → ルール後 2.10GB): **2.1GB**
- フルパス (compare --html): **5.15GB** — **HTML バンドル生成が +3GB**

内訳は report/bundle.py の3点:
1. `"rawdiffs": [d.to_dict() ...]` — RawDiff 全件 (prt 256万) の dict リスト実体化
2. `json.dumps(bundle)` の一枚岩ペイロード文字列 (478MB HTML の大半)
3. `.replace()` ×3 のフルコピー (エスケープ + テンプレート差し込み)

## 修正 (HTML byte 同一)

- bundle["rawdiffs"] は **RawDiffSet のまま保持 (遅延直列化)**
- `_payload_chunks()`: バンドル JSON をチャンクで逐次生成。RawDiffSet 値だけ
  1件ずつ直列化。チャンク境界は構造文字に接するため "</" エスケープは分割安全。
  連結結果は従来の dumps+replace と byte 同一 (テストで保証)
- `write_html()`: ファイルへ逐次書き出し (ペイロード全体の文字列を作らない)。
  CLI --html と Lambda worker はこちらを使う。`render_html()` は同一出力の
  文字列版として残置 (小規模用)
- Lambda worker (infra/runtime/handler.py): バンドル構築後に snapshot 等を
  `del` (pandas ~0.9GB を書き出し中に抱えない)、S3 へは `upload_file`
  (encode 済み全量バイト列を作らない)。/tmp 経由 (ephemeral 2GB — prt 478MB は可)

## 実測 (prt、compare --html フルパス)

| | 修正前 | 修正後 |
|---|---|---|
| ピーク RSS | 5.15GB | **2.17GB** |
| HTML (478MB) | — | **byte 同一** (generated_at 正規化のみ) |
| pytest | — | 224件 (等価性テスト test_bundle_structure に追加) |

prt 級 (stop_times 100万行・RawDiff 256万) は **Lambda 3008MB に収まる見込み**
(2.17GB + ランタイムオーバーヘッド)。デプロイ後に本番で要確認。

## 残る課題 (IN-3 後半 = 製品判断)

メモリは解けたが、**prt の HTML 自体が 478MB** で閲覧に耐えない (国内フィードは
最大 55MB)。rawdiffs 全件埋め込みが支配項。選択肢:

1. hosted bundle 化 (X1 関連): rawdiffs を別ファイルに分離しビューアが遅延取得
2. 埋め込み rawdiffs の件数上限 + ファイル別件数 (検証モードの表示仕様に影響)
3. 国際級は当面 CLI ローカル利用のみとし、Web はサイズガードで明示的に断る

いずれも表示仕様・運用の判断を伴うためコード変更は保留 (presentation R1〜R18 と
検証モードの要件に関わる)。
