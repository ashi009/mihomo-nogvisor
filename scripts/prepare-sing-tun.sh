#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
src=${1:?usage: prepare-sing-tun.sh PREPARED_MIHOMO NEW_SING_TUN_DIRECTORY}
dest=${2:?destination required}
test ! -e "$dest" || { echo "use a fresh sing-tun directory" >&2; exit 1; }
mkdir -p "$dest"
dest=$(CDPATH= cd -- "$dest" && pwd)
cd "$src"
module=github.com/metacubex/sing-tun
version=v0.4.21
go mod download "$module@$version"
cached=$(go list -m -f '{{.Dir}}' "$module@$version")
cp -R "$cached/." "$dest/"
chmod -R u+w "$dest"
for patch_file in "$repo"/patches/sing-tun/*.patch; do
    git -C "$dest" apply "$patch_file"
done
cp "$repo"/native/sing-tun/*.go "$dest/"
go mod edit "-replace=$module=$dest"
