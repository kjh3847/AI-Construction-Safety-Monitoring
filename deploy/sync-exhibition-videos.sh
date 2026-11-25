#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 || "$1" != s3://?* ]]; then
  printf 'Usage: bash deploy/sync-exhibition-videos.sh s3://BUCKET[/PREFIX]\n' >&2
  exit 2
fi
remote="${1%/}"

cd -- "$(dirname -- "$0")/.."
target=exhibition-videos
mkdir -p -- "$target"
stage="$(mktemp -d "$target/.s3-sync.XXXXXXXX")"
cleanup() {
  rm -f -- "$stage/착용.mp4" "$stage/미착용.mp4"
  rmdir -- "$stage"
}
trap cleanup EXIT

for name in 착용.mp4 미착용.mp4; do
  aws s3 cp "$remote/$name" "$stage/$name" --only-show-errors
  test -s "$stage/$name"
  chmod 0644 -- "$stage/$name"
done
for name in 착용.mp4 미착용.mp4; do
  mv -f -- "$stage/$name" "$target/$name"
done
printf 'CAM-04 착용.mp4 / CAM-05 미착용.mp4 ready\n'
