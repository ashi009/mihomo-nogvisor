#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
work=${1:?usage: prepare-native.sh NEW_WORK_DIRECTORY}
mkdir -p "$work"
work=$(CDPATH= cd -- "$work" && pwd)
rev=87d7a4365ac4f65474f573ba68dce1ee47e22e6d
test ! -e "$work/mihomo-$rev" || { echo "use a fresh work directory" >&2; exit 1; }
curl -fsSL "https://codeload.github.com/vernesong/mihomo/tar.gz/$rev" -o "$work/source.tar.gz"
tar -xzf "$work/source.tar.gz" -C "$work"
src="$work/mihomo-$rev"
for patch_file in "$repo"/patches/*.patch; do git -C "$src" apply "$patch_file"; done
cp -R "$repo/native/component/." "$src/component/"
cd "$src"
go mod edit -require=github.com/google/nftables@v0.2.1-0.20240414091927-5e242ec57806 -require=github.com/tailscale/netlink@v1.1.1-0.20240822203006-4d49adab4de7 -require=github.com/tailscale/wireguard-go@v0.0.0-20250716170648-1d0488a3d7da
"$repo/scripts/prepare-tailscale.sh" "$src" "$work/tailscale"
"$repo/scripts/prepare-sing-tun.sh" "$src" "$work/sing-tun"
printf '%s\n' "$src"
