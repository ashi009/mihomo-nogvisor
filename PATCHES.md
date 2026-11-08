# Native backend patch series

The native build uses a pinned, clean vernesong/mihomo source archive. We keep
our code in `native/component/tailnet`, and apply two small patches last:

- `patches/0001-config.patch`: decode and validate the `tailnet` configuration.
- `patches/0002-lifecycle.patch`: start/reuse the backend and shut it down.

`git apply` fails on conflicting upstream changes. There is no copied upstream
source tree to maintain. The existing rolling-release workflow is unchanged;
these scripts build the native candidate separately. Production publication
should be switched only after router acceptance.

Prepare a new directory, then build (Go 1.26.5):

    scripts/prepare-native.sh /tmp/mihomo-native-work
    scripts/build-native.sh /tmp/mihomo-native-work/mihomo-87d7a4365ac4f65474f573ba68dce1ee47e22e6d /tmp/mihomo-native

For an upstream update, change the revision in `prepare-native.sh`, reapply the
patches to the clean revision, update dependency pins only where needed, and run
the Linux tests. Keep changes to each hook in its own patch. The component is
ordinary owned Go code, rather than a patch against Tailscale internals.

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

The canonical configuration remains the parent project's Jsonnet:

    jsonnet -S ../config/native.jsonnet > /tmp/mihomo-native.yaml

`native.jsonnet` composes the existing Smart configuration with
`tailnet.libsonnet`; hostname, advertised prefixes and optional auth-key file
are parameters. No extra UCI settings or environment variables configure the
service. This is a development backend target, not the final ShellCrash capture
replacement: port/fake-IP interception extensions are a separate patch series.
Existing ShellCrash/FlClash targets keep their default behavior.

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

An unchanged configuration reload preserves the running backend. Changes to
backend settings require restart. Startup failures are reported in the core
log; upstream ApplyConfig has no error return, so a backend startup failure
currently leaves the process alive and rejects that apply. Procd integration
must account for this before cutover.

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

The advertised test address is on the container's loopback interface. These
results do not establish two-interface LAN forwarding, OpenWrt fw4 reload,
real WAN reconnection, ACL matrices, IPv6, offload, throughput or RSS. Those
remain acceptance work for deployment.

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
stripped ARM64 executable is 40,042,622 bytes (38.19 MiB); production dependencies
contain no gVisor, tsnet or netstack package.
