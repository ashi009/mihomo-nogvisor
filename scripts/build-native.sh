#!/bin/sh
#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
src=${1:?usage: build-native.sh PREPARED_SOURCE OUTPUT}
out=${2:?output required}
cd "$src"
CGO_ENABLED=0 GOOS=linux GOARCH=${GOARCH:-arm64} go build -mod=mod -trimpath -gcflags='github.com/metacubex/tailscale/...=-lang=go1.26' -tags "$(cat "$repo/scripts/native-tags")" -ldflags '-w -s -buildid=' -o "$out" .
