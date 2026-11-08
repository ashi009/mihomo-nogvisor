# Native backend patch series

The native build uses a pinned, clean vernesong/mihomo source archive. The core
revision and patched dependency versions live in `upstream.json`. We keep
our backend in `native/component/tailnet`, and apply small patches last:

- `patches/0001-config.patch`: decode and validate the `tailnet` configuration.
- `patches/0002-lifecycle.patch`: start/reuse the backend and shut it down.
- `patches/0003-capture-policy.patch`: decode the scoped interception policy and
  pass it to sing-tun's automatic route/redirect implementation.
- `patches/0004-service-lifecycle.patch`: lock supervised instances, clean stale
  network state, and exit on backend, DNS or interception startup failure.

`patches/sing-tun/0001-capture-policy.patch` adds hooks to the pinned sing-tun.
The policy implementation is owned code in `native/sing-tun`, copied
into the disposable dependency tree by `prepare-sing-tun.sh`. Both dependency
queues use local module replacements; no upstream source is committed here.

`git apply` fails on conflicting upstream changes. There is no copied upstream
source tree to maintain. The legacy ShellCrash release is manual-only;
native PR checks upload candidate artifacts without deploying to routers.

Prepare a new directory, then build (Go 1.26.5):

    source=$(scripts/prepare-native.sh /tmp/mihomo-native-work)
    scripts/build-native.sh "$source" /tmp/mihomo-native

For an upstream update, change the revision in `upstream.json`, reapply the
patches to the clean revision, update dependency pins only where needed, and run
the Linux tests. Keep changes to each hook in its own patch. The component is
ordinary owned Go code, rather than a patch against Tailscale internals.

## Upstream tracking

`track Mihomo upstream` runs daily at 09:17 Asia/Shanghai and can be dispatched
manually. It resolves vernesong's Alpha branch to an immutable SHA, carries
forward the Tailscale and sing-tun versions from that revision's go.mod, and
opens a draft PR. It never merges or deploys automatically. While an upstream
PR remains open, subsequent runs leave its branch and any manual patch rebases
untouched. A closed PR suppresses another proposal for that same revision.

The PR highlights selected upstream commit subjects for Smart, reliability,
DNS/routing and protocols, with links to each commit. `updates/<revision>.md`
contains the complete paginated commit list, dependency changes and overlaps
with our Mihomo patch hooks. Highlights describe upstream changes to review,
not verified behavior. A rewritten upstream history requires manual review.

The scheduled workflow calls `native Linux` directly, so its checks do not
depend on a bot-created PR triggering another workflow. It applies all patch
queues and runs the real native backend/capture tests on an ARM64 Linux runner.
The exact proposed commit receives a `native-linux` status with a link to the
run; passing checks mark the PR ready, failures leave it draft. Normal PRs and
main pushes also run native checks. No write token is exposed to the build job.

Repository Actions settings must permit workflows to create PRs. Only the
proposal/report jobs request write permissions. Build artifacts identify both
the upstream and local patch revision in their version string. The workflow
keeps logs, the binary and its checksum as run artifacts.

One dependency fix is maintained separately in `patches/tailscale/`.
`prepare-tailscale.sh` copies the pinned module into the disposable build
directory, applies that queue, and adds a local module replacement. The shared
module cache stays unchanged. The fix lets native injected packets pass the
GSO checksum helper when netstack is omitted; the original helper panicked on
TSMP traffic. It is covered by traffic tests against the shipping executable.

The Tailscale fork removed native TUN creation. We restore that through a pinned
native TUN dependency and an event adapter. Its otherwise-unused Linux router
code requires Go 1.26 language mode despite the fork's Go 1.20 module directive;
`build-native.sh` applies that override narrowly. No gVisor is linked in the
native executable. Build tags are explicit in `scripts/native-tags`.

## Configuration

The reusable router configuration lives in this repository's Jsonnet. Supply
the policy object (providers, groups, rules and DNS upstreams) separately:

    jsonnet --tla-code-file base=/path/to/policy.json config/router.jsonnet > /tmp/router.json

The existing private policy generator is also wired to these fragments:

    jsonnet -S ../config/native.jsonnet > /tmp/mihomo-native.yaml

`native.jsonnet` composes the existing Smart configuration with
`tailnet.libsonnet` and `capture.libsonnet`. No extra UCI settings configure the
service. Existing ShellCrash/FlClash targets keep their default behavior.
Private provider URLs, authentication keys, generated configs and saved node
state are not committed. Preserve explicit empty arrays when rendering:
`tun.inet6-address: []` disables Mihomo's default IPv6 TUN addresses, and
`tun.dns-hijack: []` leaves scoped DNS redirect in control.

The capture policy preserves 20.1's TCP/UDP ports 22/80/443/8080/8443, adds other
ports for 28.0.0.0/8 fake-IP destinations, then bypasses UDP 443/8443 even for
fake IPs. Reserved/private destinations bypass capture. IPv4 LAN/tailnet source
ranges and IPv6 DNS source ranges remain explicit in Jsonnet. DNS redirects to
1053 before destination/port exclusions; router-originated traffic is not
captured. CN traffic stays subject to the existing Mihomo rules.

Mihomo owns the routing mark through auto-redirect; do not set the global
`routing-mark`. The core installs table 100 and priorities 5206–5208 before
Tailscale's rules. It retains sing-tun's local-address exclusions and fw4
integration, including TUN acceptance before flow offload. Policy exclusions
also run before UDP conntrack mark restoration. Cleanup is limited to the three
owned rule priorities; neighbouring Tailscale and system fallback rules survive
TUN recreation, restart and shutdown. No nft or ip command wrapper
implements interception; the compiled core uses netlink. The existing fw4
helper reloads its generated include when starting and stopping.

Enrollment is interactive through the logged login URL unless `auth-key-file`
is supplied. The file and state directory must be under Mihomo's home directory.
Identity is persistent; the service uses an exclusive lock to prevent concurrent
use of its own state directory. A private offline copy of 20.1's standalone
tailscaled state retained its existing identity and browser OAuth login in the
router trial. Stop the original daemon before copying; do not point both programs
at the same state.

The backend registers `tailscale://tailnet` with Mihomo DNS. Jsonnet sends
`+.ts.net` there and retains its fake-IP exclusion. Bootstrap lookups use
Mihomo's proxy-host resolver, and return a retryable error until it is ready.
The backend leaves OS DNS configuration untouched.

Jsonnet also fixes the dashboard path and update source to Zashboard's stable
`dist-no-fonts.zip`, which uses system fonts. The dashboard update button calls
Mihomo's configured URL; omitting it would install MetaCubeXD instead.

An unchanged configuration reload preserves the running backend. Changes to
backend settings require restart. Native startup failures terminate the process
so procd can retry. DNS binds both TCP and UDP before interception starts.

## OpenWrt service

Install the native binary at `/usr/bin/mihomo`, the rendered Jsonnet config at
`/etc/mihomo/config.yaml`, `openwrt/mihomo.init` at `/etc/init.d/mihomo` (0755),
and `openwrt/mihomo.keep` at `/lib/upgrade/keep.d/mihomo`. Keep the data directory
private (0700), with config and node state files mode 0600. Retain `kmod-tun`
and `ip-full` explicitly before removing a standalone Tailscale package.

Copy dashboard assets and provider/cache data into `/etc/mihomo`, and copy the
node identity into its configured `tailnet` directory with both daemons stopped.
Stop and disable the legacy services before `/etc/init.d/mihomo enable` and
`/etc/init.d/mihomo start`. Run legacy uninstall hooks while native Mihomo is
stopped: those hooks can remove shared routing objects.

The init script validates config before starting or reloading and snapshots it
to `running.yaml`. A malformed reload leaves the running process intact.
`/etc/init.d/mihomo reload` restarts after validation; dashboard config reload
retains an unchanged tailnet. procd retries crashes every five seconds without
a retry limit. `-service` cleans stale state before startup; `-cleanup` removes
owned rules after stop and refuses to operate while the instance holds its lock.
Cleanup code is owned in `native/component/native`, outside upstream patches.

Startup diagnostics go to `logread -e mihomo`. Jsonnet sets console level to
warning; dashboard log subscriptions can still request info/debug events.
The sysupgrade retention list includes itself, the binary, init script and
complete data directory. There is no separate UCI configuration or LuCI app.

## Linux acceptance so far

On the ARM64 Docker Linux VM, using disposable local control/DERP/STUN services:

    tests/linux/run.sh PREPARED_SOURCE /tmp/mihomo-native-test

This rebuilds the native executable and a separate test executable. gVisor is
included only in the test executable for the peer, never in the shipping one.
Test helpers need a language override and vet exception because the fork's
unused test sources exceed its declared language version.

Passed: native TUN creation, TCP/UDP and ICMP to an advertised address, MagicDNS
through Mihomo, exclusive state access, restart identity, unchanged reload,
identity-change rejection, and TUN removal. A subprocess test exercises the
actual no-gVisor Mihomo executable: configuration loading, local-tailnet join,
its DNS listener, TSMP/ICMP traffic and SIGTERM cleanup. The traffic check
reproduced the stripped-build panic before the dependency patch and passed
afterward. The test uses nftables, matching 20.1's selected firewall backend.

The tailnet-only fixture uses a loopback destination. A separate privileged,
network-isolated container creates client and target namespaces for actual
forwarding. Its shipping-binary tests cover every selected port, fake-IP
precedence, UDP exceptions, private destinations, source scope, router output,
IPv6 bypass, IPv4/IPv6 TCP/UDP DNS interception, successful TCP/UDP forwarding,
config/firewall reload, TUN recreation, forced-kill restart and cleanup. A
regression fixture protects foreign routing rules at priorities 5210 and 32768;
the previous cleanup failed it and the narrowed cleanup passes. The privileged flag
is confined to this disposable Linux test container.

Service tests also exercise cleanup locking, repeated offline cleanup after
SIGKILL, Tailscale rule removal and identity-preserving restart, and DNS bind
failure before interception can be enabled.

## 20.1 trial, 2026-11-08

The candidate ran temporarily with ShellCrash and standalone tailscaled stopped,
under a 90-second rollback guard. It reused an offline copy of the saved node
state and reached Running without a new login. Peer 100.99.10.1 and remote
router LAN address 192.168.10.1 answered all three ICMP probes. From 10.1, TSMP
to the candidate and ICMP to its advertised LAN address 192.168.20.1 worked.
Mihomo's temporary DNS listener resolved both routers' MagicDNS names over UDP,
the remote name over TCP, and an ordinary public domain.

The first trial exposed the no-netstack panic fixed in the dependency patch.
The corrected Linux regression and router trial passed. This exercised router
addresses, not forwarding to a separate LAN host, and did not replace ShellCrash
transparent capture. Original services were restored after the trial. The
backend-only stripped ARM64 executable was 40,042,622 bytes (38.19 MiB).

## Combined interception trial, 2026-11-08

The final combined stripped executable is 40,042,622 bytes (38.19 MiB), with no
gVisor, tsnet or netstack in its production dependency graph. A three-minute
20.1 trial stopped both original services and ran the full private Jsonnet
policy with an offline copy of the node state and provider/cache files.

- Interface-bound LAN HTTPS through a router-issued fake IP returned 204 and
  appeared in Mihomo's log; Zashboard returned 200.
- MagicDNS worked over UDP and TCP; 10.1 reached a separate host on 20.1's LAN.
- Real fw4 and unchanged config reloads preserved interception and DNS.
- A follow-up trial changed TUN MTU through Jsonnet, recreated the TUN, retained
  Tailscale's rules and peer connectivity, and returned another LAN HTTPS 204.
- Native UDP capture reached the TUN; explicit real/fake-IP UDP 443/8443 probes
  hit the bypass counters. TUN acceptance preceded fw4 flow offload.
- The timed guard restored both original services and routes. The original
  core hash matched, and temporary files and the copied identity were removed.

`tests/openwrt/trial.sh` records the bounded trial procedure for cito-102. Stage
a freshly rendered config and binary first; run the guard under procd so SSH
loss does not prevent rollback. The router lacks veth support, so live traffic
used a physical LAN client; Linux namespace tests remain in Docker. The candidate
was not installed as the boot service. Long-duration stability, WAN reconnects,
reboots, throughput and Twingate application acceptance remain unmeasured.

## Permanent 20.1 cutover, 2026-11-09

The combined service is installed at `/usr/bin/mihomo`, enabled under procd,
and passed a router reboot. The stripped ARM64 binary is 40,108,158 bytes
(38.25 MiB), SHA-256
`70b917f070a60bc5e7f01ed4460323069e0e6e3bf792e5c613ba643689b8b2ef`.

On the installed service, invalid reload retained the PID, valid reload and
stop/start succeeded, and SIGKILL triggered recovery with exactly one set of
capture and tailnet rules. After reboot, LAN HTTPS returned 204, Zashboard 200,
MagicDNS retained the node address, and 10.1 reached a separate host on 20.1's
advertised LAN. The process runs from flash with RssShmem 0 and holds the
persistent cache open.

ShellCrash was stopped and uninstalled through its interactive CLI; its old
configuration/subscriptions were retained. Its scripts, service, profile alias
and scheduled jobs are gone. Standalone Tailscale and both LuCI packages were
removed, retaining the existing tailscale0 firewall zone and required routing
packages. A private configuration recovery archive remains on the router.
No changes were deployed to 10.1 or 30.1. Sustained throughput, WAN reconnects
and application-specific Twingate acceptance remain unmeasured.

The native target explicitly enables `unified-delay`, matching 10.1 and
FlClash. Before this setting, the same two Japan nodes and HTTPS health-check
URL measured 429–478 ms on 20.1 versus 102–116 ms on 10.1. Changing only this
setting produced 105–110 ms on 20.1, 101–108 ms on 10.1 and 108–121 ms in
FlClash across six matched tests. This changes the reported timing to a second
request on the established connection; it does not reduce connection setup
latency. 10.1 was used read-only as the comparison router.
