#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=${1:?usage: prepare-native.sh NEW_WORK_DIRECTORY}
mkdir -p "$work"
work=$(CDPATH= cd -- "$work" && pwd)
rev=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$repo/upstream.json")
test ! -e "$work/mihomo-$rev" || { echo "use a fresh work directory" >&2; exit 1; }
curl -fsSL "https://codeload.github.com/vernesong/mihomo/tar.gz/$rev" -o "$work/source.tar.gz"
tar -xzf "$work/source.tar.gz" -C "$work"
src="$work/mihomo-$rev"
printf '%s\n' "$rev" > "$src/.upstream-revision"
for patch_file in "$repo"/patches/*.patch; do git -C "$src" apply "$patch_file"; done
cp -R "$repo/native/component/." "$src/component/"
cd "$src"
"$repo/scripts/prepare-tailscale.sh" "$src" "$work/tailscale"
"$repo/scripts/prepare-sing-tun.sh" "$src" "$work/sing-tun"
printf '%s\n' "$src"
