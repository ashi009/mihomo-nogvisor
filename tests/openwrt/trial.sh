#!/bin/sh
# Bounded cito-102 acceptance trial. Run under procd, independently of SSH.
# Stage mihomo and a Jsonnet-generated config.yaml in the trial directory first.
set -eu
umask 077
trial=/tmp/mihomo-capture-trial
duration=${1:-180}
case "$duration" in ''|*[!0-9]*) exit 2;; esac
cpid=
cleanup() {
    trap - 0 1 2 15
    set +e
    if [ -n "$cpid" ] && kill -0 "$cpid" 2>/dev/null; then
        kill -TERM "$cpid"
        sleep 3
        kill -KILL "$cpid" 2>/dev/null
        wait "$cpid" 2>/dev/null
    fi
    # Hard-kill fallback; only candidate-owned objects, before originals restart.
    nft delete table inet mihomo 2>/dev/null
    rm -f /etc/nftables.d/0-mihomo-auto-redirect.nft
    for priority in 5206 5207 5208; do ip -4 rule del priority "$priority" 2>/dev/null; done
    ip -4 route flush table 100
    ip link del mihomo0 2>/dev/null
    fw4 reload > "$trial/rollback-firewall.log" 2>&1
    /etc/init.d/tailscale start
    /etc/init.d/shellcrash start
    date > "$trial/restored"
}
trap cleanup 0 1 2 15
/etc/init.d/shellcrash stop
/etc/init.d/tailscale stop
for n in 1 2 3 4 5; do pidof tailscaled >/dev/null || break; sleep 1; done
if pidof tailscaled >/dev/null; then exit 1; fi
mkdir -p "$trial/tailnet"
cp /etc/tailscale/tailscaled.state "$trial/tailnet/tailscaled.state"
for dir in proxies rules ruleset ui; do cp -R "/etc/ShellCrash/$dir" "$trial/"; done
cp /etc/ShellCrash/cache.db "$trial/cache.db"
"$trial/mihomo" -d "$trial" -f "$trial/config.yaml" > "$trial/core.log" 2>&1 &
cpid=$!
echo "$cpid" > "$trial/core.pid"
date > "$trial/started"
i=0
while [ "$i" -lt "$duration" ] && kill -0 "$cpid" 2>/dev/null; do sleep 1; i=$((i+1)); done
