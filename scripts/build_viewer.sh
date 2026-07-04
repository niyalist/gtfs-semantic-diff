#!/bin/sh
# ビューアを再ビルドしてパッケージ内テンプレートを更新する
set -e
cd "$(dirname "$0")/../viewer"
npm install --no-audit --no-fund
npm run build
cp dist/index.html ../src/gtfs_semdiff/report/viewer_template.html
echo "updated src/gtfs_semdiff/report/viewer_template.html"
