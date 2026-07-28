#!/usr/bin/env bash
# 撮影済み webm を README/docs 埋め込み用の GIF と mp4 に変換する。
# 使い方: scripts/demo_capture/convert.sh [シーン名...]   （省略時は out/video/*.webm 全部）
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p out/gif out/mp4

files=()
if [ $# -gt 0 ]; then
  for n in "$@"; do files+=("out/video/$n.webm"); done
else
  files=(out/video/*.webm)
fi

for f in "${files[@]}"; do
  name="$(basename "$f" .webm)"
  # GIF: palettegen/paletteuse で 256色最適化。fps10 / 幅960 で 3MB 以下を狙う
  ffmpeg -y -i "$f" -vf "fps=10,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
    "out/gif/$name.gif" 2>/dev/null
  # mp4: 動画編集ソフトへの取り込み用（h264・無音）
  ffmpeg -y -i "$f" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "out/mp4/$name.mp4" 2>/dev/null
  printf '%s: gif=%s mp4=%s\n' "$name" \
    "$(du -h "out/gif/$name.gif" | cut -f1)" "$(du -h "out/mp4/$name.mp4" | cut -f1)"
done
