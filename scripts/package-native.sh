#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
binary=${1:?usage: package-native.sh BINARY OUTPUT_DIRECTORY [APK_ARCH]}
out=${2:?output directory required}
arch=${3:-aarch64_cortex-a53}
binary=$(CDPATH= cd -- "$(dirname "$binary")" && pwd)/$(basename "$binary")
mkdir -p "$out"
out=$(CDPATH= cd -- "$out" && pwd)
revision=$(git -C "$repo" rev-parse HEAD)
epoch=$(git -C "$repo" show -s --format=%ct HEAD)
version="0.$epoch~$(printf '%.12s' "$revision")-r0"
image=$(cat "$repo/openwrt/apk-image")
docker run --rm -i --network none \
    -v "$repo:/repo:ro" -v "$binary:/binary:ro" -v "$out:/out" \
    "$image" sh -s -- "$version" "$arch" "$revision" "$epoch" <<'SH'
set -eu
version=$1
arch=$2
revision=$3
epoch=$4
mkdir -p /stage/usr/bin /stage/usr/libexec /stage/usr/share/mihomo /stage/etc/init.d /stage/lib/upgrade/keep.d /stage/lib/apk/packages
cp /binary /stage/usr/bin/mihomo
cp /repo/openwrt/tailnet-firewall.uci /stage/usr/share/mihomo/tailnet-firewall.uci
cp /repo/openwrt/mihomo-firewall /stage/usr/libexec/mihomo-firewall
chmod 755 /stage/usr/libexec/mihomo-firewall
cp /repo/openwrt/mihomo.init /stage/etc/init.d/mihomo
cp /repo/openwrt/mihomo.keep /stage/lib/upgrade/keep.d/mihomo
chmod 755 /stage/usr/bin/mihomo /stage/etc/init.d/mihomo
chmod 644 /stage/lib/upgrade/keep.d/mihomo
(cd /stage && find . -type f | sed 's|^\.||' | sort) > /stage/lib/apk/packages/mihomo-native.list
set --
for event in pre-install post-install pre-upgrade post-upgrade pre-deinstall; do
    { printf '#!/bin/sh\nset -eu\nset -- %s "$@"\n' "$event"; cat /repo/openwrt/apk-hooks.sh; } > "/tmp/$event"
    set -- "$@" --script "$event:/tmp/$event"
done
apk mkpkg --compat 3.0.0 --compression deflate:9 \
    --info name:mihomo-native --info "version:$version" --info "arch:$arch" \
    --info 'description:Mihomo with native Tailscale subnet routing and scoped interception' \
    --info license:GPL-3.0-or-later --info origin:mihomo-nogvisor \
    --info url:https://github.com/ashi009/mihomo-nogvisor \
    --info "repo-commit:$revision" --info "build-time:$epoch" \
    --info 'depends:busybox uci procd kmod-tun nftables firewall4 ip-full ca-bundle !mihomo !tailscale' \
    "$@" --files /stage --output "/out/mihomo-native-$version.apk"
SH
printf '%s\n' "$out/mihomo-native-$version.apk"
