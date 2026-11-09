#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
src=${1:?usage: tests/linux/run.sh PREPARED_SOURCE WORK_DIRECTORY}
work=${2:?work directory required}
mkdir -p "$work"
jsonnet -J "$repo/config" "$repo/tests/linux/config.jsonnet" > "$work/config.json"
jsonnet -J "$repo/config" "$repo/tests/linux/capture.jsonnet" > "$work/capture.json"
jsonnet -J "$repo/config" -S -e 'local f=import "firewall.libsonnet"; local c=import "capture.jsonnet"; f(c+{tailnet:{enable:true,interface:"tailscale0"}})' -J "$repo/tests/linux" > "$work/firewall.uci"
"$repo/scripts/build-native.sh" "$src" "$work/mihomo"
cd "$src"
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go list -mod=mod -deps -tags "$(paste -sd, "$repo/scripts/native-tags")" . > "$work/runtime-deps.txt"
grep -qx 'tailscale.com/feature/portmapper' "$work/runtime-deps.txt" || {
    echo 'native build is missing Tailscale port mapping support' >&2
    exit 1
}
if grep -E '(^|/)gvisor(/|$)|^github.com/metacubex/tailscale(/|$)|^tailscale.com/(tsnet|wgengine/netstack)$' "$work/runtime-deps.txt"; then
    echo 'unexpected userspace stack or fork in the native dependency graph' >&2
    exit 1
fi
go test -mod=mod tailscale.com/net/dnscache -run TestResolverLookupHook -count=1
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go test -mod=mod -tags with_gvisor,no_tailscale -c ./component/tailnet -o "$work/native.test"

docker build -t mihomo-native-test:local "$repo/tests/linux"
docker run --rm --cap-add NET_ADMIN --device /dev/net/tun --sysctl net.ipv4.ip_forward=1 --sysctl net.ipv6.conf.all.forwarding=1 -v "$work:/test:ro" mihomo-native-test:local sh -c 'ip addr add 192.0.2.1/24 dev lo; /test/native.test -test.v -test.timeout=90s'
docker run --rm --privileged --network none --sysctl net.ipv4.ip_forward=1 --sysctl net.ipv6.conf.all.forwarding=1 -v "$work:/test:ro" -v "$repo/tests/linux:/scripts:ro" -v "$repo/openwrt:/package:ro" mihomo-native-test:local python3 /scripts/capture.py
