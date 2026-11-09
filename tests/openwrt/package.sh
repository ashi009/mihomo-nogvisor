#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
package=${1:?usage: package.sh APK_FILE}
package=$(CDPATH= cd -- "$(dirname "$package")" && pwd)/$(basename "$package")
fragment=$(mktemp)
trap 'rm -f "$fragment"' EXIT
jsonnet -J "$repo/config" -S -e 'local f=import "firewall.libsonnet"; f((import "capture.libsonnet")()+(import "tailnet.libsonnet")())' > "$fragment"
docker run --rm -i --cap-add NET_ADMIN --network none -v "$package:/candidate.apk:ro" -v "$repo:/repo:ro" -v "$fragment:/firewall.uci:ro" \
    mihomo-native-test:local sh -s <<'SH'
set -eu
mkdir -p /etc/init.d /etc/mihomo/tailnet
cat > /etc/rc.common <<'RC'
#!/bin/sh
case "$2" in
    running) test -e /tmp/service-running ;;
    start) /usr/libexec/mihomo-firewall apply || exit 1; echo start >> /tmp/service-events; touch /tmp/service-running ;;
    stop) echo stop >> /tmp/service-events; rm -f /tmp/service-running ;;
    enable) echo enable >> /tmp/service-events; touch /tmp/service-enabled ;;
    disable) echo disable >> /tmp/service-events; rm -f /tmp/service-enabled ;;
esac
RC
cp /repo/openwrt/mihomo.init /etc/init.d/mihomo
chmod 755 /etc/init.d/mihomo
printf 'config defaults\n option input ACCEPT\n option output ACCEPT\n option forward REJECT\nconfig zone lan\n option name lan\n option device br-lan\n' > /etc/config/firewall
printf 'config interface lan\n option device br-lan\n' > /etc/config/network
cp /firewall.uci /etc/mihomo/firewall.uci
fw4 start
printf 'external jsonnet output\n' > /etc/mihomo/config.yaml
printf 'existing identity\n' > /etc/mihomo/tailnet/tailscaled.state
sha256sum /etc/mihomo/config.yaml /etc/mihomo/tailnet/tailscaled.state > /tmp/state.sha256
arch=$(apk --print-arch)
apk mkpkg --info name:openwrt-test-deps --info version:1-r0 --info "arch:$arch" \
    --info 'provides:uci=1 procd=1 kmod-tun=1 firewall4=1 ip-full=1 ca-bundle=1' \
    --output /tmp/deps.apk
printf 'aarch64_cortex-a53\n%s\n' "$arch" > /etc/apk/arch
touch /tmp/service-running
apk add --arch aarch64_cortex-a53 --allow-untrusted --repositories-file /dev/null /tmp/deps.apk /candidate.apk
printf 'stop\nenable\nstart\n' > /tmp/expected-events
cmp /tmp/service-events /tmp/expected-events
sha256sum -c /tmp/state.sha256
apk info --who-owns /usr/bin/mihomo

apk del --no-network --repositories-file /dev/null mihomo-native
mkdir -p /tmp/old/etc/init.d
cp /repo/openwrt/mihomo.init /tmp/old/etc/init.d/mihomo
chmod 755 /tmp/old/etc/init.d/mihomo
apk mkpkg --info name:mihomo-native --info version:0-r0 --info arch:aarch64_cortex-a53 \
    --files /tmp/old --output /tmp/old.apk
apk add --allow-untrusted --repositories-file /dev/null /tmp/old.apk
touch /tmp/service-running /tmp/service-enabled
: > /tmp/service-events
apk add --allow-untrusted --repositories-file /dev/null /candidate.apk
printf 'stop\nstart\n' > /tmp/expected-events
cmp /tmp/service-events /tmp/expected-events
sha256sum -c /tmp/state.sha256

rm -f /tmp/service-running
apk add --allow-untrusted --repositories-file /dev/null /tmp/old.apk
: > /tmp/service-events
apk add --allow-untrusted --repositories-file /dev/null /candidate.apk
test ! -s /tmp/service-events
test ! -e /tmp/service-running

apk del --no-network --repositories-file /dev/null mihomo-native
test ! -e /usr/bin/mihomo
! uci show firewall | grep mihomo_
test ! -e /tmp/service-enabled
sha256sum -c /tmp/state.sha256
printf 'PASS APK install, upgrade hooks, stopped-service preservation and removal\n'
SH
