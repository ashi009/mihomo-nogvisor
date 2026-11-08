#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
src=${1:?usage: build-native.sh PREPARED_SOURCE OUTPUT}
out=${2:?output required}
cd "$src"
revision=$(cat .upstream-revision)
patch_revision=$(git -C "$repo" rev-parse --short=12 HEAD)
git -C "$repo" diff --quiet HEAD -- || patch_revision="$patch_revision-dirty"
version="alpha-smart-$(printf '%.12s' "$revision")-native-$patch_revision"
CGO_ENABLED=0 GOOS=linux GOARCH=${GOARCH:-arm64} go build -mod=mod -trimpath -gcflags='github.com/metacubex/tailscale/...=-lang=go1.26' -tags "$(cat "$repo/scripts/native-tags")" -ldflags "-X github.com/metacubex/mihomo/constant.Version=$version -w -s -buildid=" -o "$out" .
