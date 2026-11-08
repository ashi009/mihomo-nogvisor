# Native build

Patch rationale and provenance live in the patch headers:
[mihomo](patches/mihomo/), [sing-tun](patches/sing-tun/),
[tailscale](patches/tailscale/).

- [Upstream pins](upstream.json)
- [Source preparation](scripts/prepare-native.sh)
- [Build](scripts/build-native.sh) and [Linux tests](tests/linux/run.sh)
- [Jsonnet configuration](config/)
- [Upstream update workflow](.github/workflows/upstream.yml)
- [CI and binary size reports](.github/workflows/native.yml)
