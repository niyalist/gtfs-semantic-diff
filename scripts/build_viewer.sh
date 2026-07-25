#!/bin/sh
# ビューアを再ビルドしてパッケージ内テンプレートを更新する。
# テストが落ちたらテンプレートを更新しない (ui_quality.md S4)
set -e
cd "$(dirname "$0")/../viewer"
npm install --no-audit --no-fund
npm test
npm run build
cp dist/index.html ../src/gtfs_semantic_diff/report/viewer_template.html
echo "updated src/gtfs_semantic_diff/report/viewer_template.html"
