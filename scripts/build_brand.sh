#!/bin/bash
# ブランドアセット (favicon / OGP 画像) の再生成。要: rsvg-convert, ImageMagick
set -euo pipefail
cd "$(dirname "$0")/.."
rsvg-convert scripts/brand/favicon.svg -w 180 -h 180 -o web/apple-touch-icon.png
rsvg-convert scripts/brand/favicon.svg -w 32 -h 32 -o /tmp/fav32.png
rsvg-convert scripts/brand/favicon.svg -w 16 -h 16 -o /tmp/fav16.png
magick /tmp/fav16.png /tmp/fav32.png web/favicon.ico
cp scripts/brand/favicon.svg web/favicon.svg
rsvg-convert scripts/brand/ogp.svg -w 1200 -h 630 -o web/ogp.png
echo "generated: web/favicon.svg web/favicon.ico web/apple-touch-icon.png web/ogp.png"
