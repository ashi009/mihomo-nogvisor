#!/bin/sh
#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
src=${1:?usage: tests/linux/run.sh PREPARED_SOURCE WORK_DIRECTORY}
work=${2:?work directory required}
mkdir -p "$work"
jsonnet -J "$repo/config" "$repo/tests/linux/config.jsonnet" > "$work/config.json"
jsonnet -J "$repo/config" "$repo/tests/linux/capture.jsonnet" > "$work/capture.json"
"$repo/scripts/build-native.sh" "$src" "$work/mihomo"
cd "$src"
go mod edit -go=1.25.1 -require=github.com/axiomhq/hyperloglog@v0.3.0 -require=github.com/go4org/hashtriemap@v0.0.0-20260925222741-44e5305f85d9 -require=github.com/kamstrup/intmap@v0.5.2 -require=github.com/dgryski/go-metro@v0.0.0-20250106013310-edb8663e5e33
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go test -mod=mod -vet=off -gcflags='github.com/metacubex/tailscale/...=-lang=go1.26' -tags with_gvisor -c ./component/tailnet -o "$work/native.test"
docker build -t mihomo-native-test:local "$repo/tests/linux"
docker run --rm --cap-add NET_ADMIN --device /dev/net/tun --sysctl net.ipv4.ip_forward=1 --sysctl net.ipv6.conf.all.forwarding=1 -v "$work:/test:ro" mihomo-native-test:local sh -c 'ip addr add 192.0.2.1/24 dev lo; /test/native.test -test.v -test.timeout=90s'
docker run --rm --privileged --network none --sysctl net.ipv4.ip_forward=1 --sysctl net.ipv6.conf.all.forwarding=1 -v "$work:/test:ro" -v "$repo/tests/linux:/scripts:ro" mihomo-native-test:local python3 /scripts/capture.py
