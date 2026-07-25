#!/usr/bin/env bash
# Print the next ADR number, zero-padded to 4 digits, based on the existing ADRs in docs/adr/.
#
# Usage:
#   scripts/next-adr-number.sh [adr-directory]
#   (adr-directory defaults to docs/adr)
#
# Matches file names of the form `NNNN-<slug>.md`, where NNNN is 4 digits.
# If the directory does not exist, creates it and prints 0001.
set -euo pipefail

adr_dir="${1:-docs/adr}"

if [ ! -d "$adr_dir" ]; then
  mkdir -p "$adr_dir"
  printf '0001\n'
  exit 0
fi

max=0
for f in "$adr_dir"/[0-9][0-9][0-9][0-9]-*.md; do
  # When nothing matches, the glob stays unexpanded, so skip it
  [ -e "$f" ] || continue

  n="$(basename "$f")"
  n="${n%%-*}"
  # Prefix with 10# so a leading zero is not read as octal (e.g. 0008)
  n=$((10#$n))

  if [ "$n" -gt "$max" ]; then
    max="$n"
  fi
done

printf '%04d\n' "$((max + 1))"
