#!/usr/bin/env bash
# docs/adr/ 配下の既存 ADR から次の連番をゼロパディング4桁で出力する。
#
# 使い方:
#   scripts/next-adr-number.sh [ADRディレクトリ]
#   （ADRディレクトリの既定値は docs/adr）
#
# 対象とするファイル名は `NNNN-<slug>.md`（NNNN は4桁数字）。
# ディレクトリが存在しない場合は作成し、0001 を出力する。
set -euo pipefail

adr_dir="${1:-docs/adr}"

if [ ! -d "$adr_dir" ]; then
  mkdir -p "$adr_dir"
  printf '0001\n'
  exit 0
fi

max=0
for f in "$adr_dir"/[0-9][0-9][0-9][0-9]-*.md; do
  # マッチするファイルが無い場合、glob は展開されずそのまま残るのでスキップする
  [ -e "$f" ] || continue

  n="$(basename "$f")"
  n="${n%%-*}"
  # 先頭のゼロを8進数として解釈させないため 10# を付ける（例: 0008）
  n=$((10#$n))

  if [ "$n" -gt "$max" ]; then
    max="$n"
  fi
done

printf '%04d\n' "$((max + 1))"
