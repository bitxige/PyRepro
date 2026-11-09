#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
source_file="$(find "$root" -maxdepth 1 -type f -name '*.py' -printf '%f\n')"
target_python="${TARGET_PYTHON:-python3}"

case "$source_file" in
  method.py) expected='ValueError: method fixture failure' ;;
  if_case.py) expected='ValueError: if fixture failure' ;;
  container.py) expected='ValueError: container fixture failure' ;;
  *) echo "unexpected input: $source_file" >&2; exit 1 ;;
esac

output="$(PYTHONDONTWRITEBYTECODE=1 "$target_python" "$root/$source_file" 2>&1)" || status=$?
status="${status:-0}"
if [[ "$status" -eq 1 ]] \
  && grep -Fq "$expected" <<<"$output" \
  && grep -Fq "$source_file\", line" <<<"$output" \
  && grep -Fq 'in trigger' <<<"$output"; then
  exit 0
fi

printf '%s\n' "$output" >&2
exit 1
