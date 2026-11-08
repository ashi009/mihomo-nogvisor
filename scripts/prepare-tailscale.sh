#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
src=${1:?usage: prepare-tailscale.sh PREPARED_MIHOMO NEW_TAILSCALE_DIRECTORY}
dest=${2:?destination required}
test ! -e "$dest" || { echo "use a fresh Tailscale directory" >&2; exit 1; }
mkdir -p "$dest"
dest=$(CDPATH= cd -- "$dest" && pwd)
cd "$src"
module=github.com/metacubex/tailscale
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["dependencies"][sys.argv[2]])' "$repo/upstream.json" "$module")
go mod download "$module@$version"
cached=$(go list -m -f '{{.Dir}}' "$module@$version")
cp -R "$cached/." "$dest/"
chmod -R u+w "$dest"
for patch_file in "$repo"/patches/tailscale/*.patch; do
    git -C "$dest" apply "$patch_file"
done
go mod edit "-replace=$module=$dest"
