//go:build linux && with_gvisor

package tailnet

import (
	"context"
	"github.com/metacubex/mihomo/component/resolver"
	"io"
	"net"
	"net/http/httptest"
	"net/netip"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"bytes"
	"encoding/json"
	C "github.com/metacubex/mihomo/constant"
	mdns "github.com/metacubex/mihomo/dns"
	D "github.com/miekg/dns"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"tailscale.com/derp/derpserver"
	"tailscale.com/ipn"
	"tailscale.com/net/netns"
	"tailscale.com/net/stun/stuntest"
	"tailscale.com/tailcfg"
	"tailscale.com/tsnet"
	"tailscale.com/tstest/integration/testcontrol"
	"tailscale.com/types/key"
	"tailscale.com/types/logger"
	"tailscale.com/types/nettype"
)

// This probe uses only a disposable local control plane, local DERP/STUN,
// and loopback backends. It never joins the production tailnet.
func TestNativeSubnetAndMagicDNS(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	netns.SetEnabled(false)
	defer netns.SetEnabled(true)
	derp := derpserver.New(key.NewNode(), logger.Discard)
	defer derp.Close()
	relay := httptest.NewTLSServer(derpserver.Handler(derp))
	defer relay.Close()
	stun, closeStun := stuntest.ServeWithPacketListener(t, nettype.Std{})
	defer closeStun()
	control := &testcontrol.Server{
		DERPMap:        &tailcfg.DERPMap{Regions: map[int]*tailcfg.DERPRegion{1: {RegionID: 1, RegionCode: "test", Nodes: []*tailcfg.DERPNode{{Name: "t1", RegionID: 1, HostName: "127.0.0.1", IPv4: "127.0.0.1", IPv6: "none", STUNPort: stun.Port, STUNTestIP: "127.0.0.1", DERPPort: relay.Listener.Addr().(*net.TCPAddr).Port, InsecureForTests: true}}}}},
		DNSConfig:      &tailcfg.DNSConfig{Proxied: true},
		MagicDNSDomain: "probe.ts.net", Logf: logger.Discard,
	}
	control.HTTPTestServer = httptest.NewServer(control)
	defer control.HTTPTestServer.Close()
	C.SetHomeDir(t.TempDir())
	// Only Mihomo's bootstrap resolver knows this control-plane hostname.
	bootstrap, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	var bootstrapQueries atomic.Int32
	bootstrapDNS := &D.Server{PacketConn: bootstrap, Handler: D.HandlerFunc(func(w D.ResponseWriter, q *D.Msg) {
		response := new(D.Msg)
		response.SetReply(q)
		if len(q.Question) == 1 && q.Question[0].Name == "control.native.test." {
			bootstrapQueries.Add(1)
			if q.Question[0].Qtype == D.TypeA {
				response.Answer = []D.RR{&D.A{Hdr: D.RR_Header{Name: q.Question[0].Name, Rrtype: D.TypeA, Class: D.ClassINET, Ttl: 1}, A: net.IPv4(127, 0, 0, 1)}}
			}
		}
		w.WriteMsg(response)
	})}
	go bootstrapDNS.ActivateAndServe()
	defer bootstrapDNS.Shutdown()
	previousResolver := resolver.ProxyServerHostResolver
	resolver.ProxyServerHostResolver = mdns.NewResolver(mdns.Config{Main: []mdns.NameServer{{Net: "udp", Addr: bootstrap.LocalAddr().String()}}})
	defer func() { resolver.ProxyServerHostResolver = previousResolver }()
	raw, err := os.ReadFile("/test/config.json")
	if err != nil {
		t.Fatal(err)
	}
	var input struct {
		Tailnet Config `json:"tailnet"`
	}
	if err = json.Unmarshal(raw, &input); err != nil {
		t.Fatal(err)
	}
	cfg := input.Tailnet
	cfg.ControlURL = strings.Replace(control.HTTPTestServer.URL, "127.0.0.1", "control.native.test", 1)
	cfg.StateDir = t.TempDir()
	gateway, err := Start(cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer gateway.Close()
	deadline := time.Now().Add(20 * time.Second)
	for gateway.backend.State() != ipn.Running {
		if time.Now().After(deadline) {
			t.Fatal("native backend not running")
		}
		time.Sleep(50 * time.Millisecond)
	}
	if bootstrapQueries.Load() == 0 {
		t.Fatal("control plane bypassed Mihomo bootstrap DNS")
	}
	status := gateway.backend.Status()
	prefix := cfg.AdvertiseRoutes[0]
	control.SetSubnetRoutes(status.Self.PublicKey, []netip.Prefix{prefix})
	if _, err := net.InterfaceByName(cfg.Interface); err != nil {
		t.Fatal(err)
	}

	tcpBackend, err := net.Listen("tcp", "192.0.2.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer tcpBackend.Close()
	go func() {
		for {
			c, err := tcpBackend.Accept()
			if err != nil {
				return
			}
			go func() { defer c.Close(); io.Copy(c, c) }()
		}
	}()
	udpBackend, err := net.ListenPacket("udp", "192.0.2.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer udpBackend.Close()
	go func() {
		b := make([]byte, 4096)
		for {
			n, a, e := udpBackend.ReadFrom(b)
			if e != nil {
				return
			}
			udpBackend.WriteTo(b[:n], a)
		}
	}()

	peer := &tsnet.Server{Dir: t.TempDir(), Hostname: "probe-peer", ControlURL: control.HTTPTestServer.URL, Logf: logger.Discard}
	defer peer.Close()
	if _, err := peer.Up(ctx); err != nil {
		t.Fatal(err)
	}
	pc, err := peer.LocalClient()
	if err != nil {
		t.Fatal(err)
	}
	if _, err = pc.EditPrefs(ctx, &ipn.MaskedPrefs{Prefs: ipn.Prefs{RouteAll: true}, RouteAllSet: true}); err != nil {
		t.Fatal(err)
	}
	for _, network := range []string{"tcp", "udp"} {
		t.Run(network, func(t *testing.T) {
			var last error
			for attempt := 0; attempt < 20; attempt++ {
				c, e := peer.Dial(ctx, network, func() string {
					if network == "tcp" {
						return tcpBackend.Addr().String()
					}
					return udpBackend.LocalAddr().String()
				}())
				if e == nil {
					c.SetDeadline(time.Now().Add(time.Second))
					_, e = c.Write([]byte("subnet-probe"))
					if e == nil {
						b := make([]byte, 12)
						_, e = io.ReadFull(c, b)
						if e == nil && string(b) != "subnet-probe" {
							t.Fatalf("bad echo %q", b)
						}
					}
					c.Close()
				}
				if e == nil {
					return
				}
				last = e
				time.Sleep(100 * time.Millisecond)
			}
			t.Fatal(last)
		})
	}
	t.Run("mihomo_magic_dns", func(t *testing.T) {
		resolver := mdns.NewResolver(mdns.Config{Main: []mdns.NameServer{{Net: "tailscale", Addr: cfg.Name}}})
		q := new(D.Msg)
		q.SetQuestion("probe-peer.probe.ts.net.", D.TypeA)
		answer, err := resolver.ExchangeContext(ctx, q)
		if err != nil {
			t.Fatal(err)
		}
		peer4, _ := peer.TailscaleIPs()
		for _, rr := range answer.Answer {
			if a, ok := rr.(*D.A); ok && a.A.String() == peer4.String() {
				return
			}
		}
		t.Fatalf("no peer A record: %v", answer)
	})
	t.Run("icmp", func(t *testing.T) {
		result, err := pc.Ping(ctx, netip.MustParseAddr("192.0.2.1"), tailcfg.PingICMP)
		if err != nil {
			t.Fatal(err)
		}
		if result.Err != "" {
			t.Fatal(result.Err)
		}
	})
	t.Run("exclusive_state", func(t *testing.T) {
		other, err := Start(cfg)
		if err == nil {
			other.Close()
			t.Fatal("duplicate state accepted")
		}
	})

	t.Run("unchanged_reload", func(t *testing.T) {
		active = gateway
		defer func() { active = nil }()
		before := gateway.backend
		if err := Apply(cfg); err != nil {
			t.Fatal(err)
		}
		if active.backend != before {
			t.Fatal("reload restarted tailnet")
		}
		changed := cfg
		changed.Hostname = "changed"
		if _, err := Normalize(changed); err == nil {
			t.Fatal("identity change accepted without restart")
		}
	})

	t.Run("shipping_binary_dns_traffic_and_shutdown", func(t *testing.T) {
		// Native route managers share OS routing tables; replace, never overlap.
		gateway.Close()
		cli := cfg
		cli.Hostname = "native-cli"
		cli.Interface = "tailcli0"
		cli.StateDir = "state"
		cli.Port = 0
		home := t.TempDir()
		packet, err := net.ListenPacket("udp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		addr := packet.LocalAddr().String()
		packet.Close()
		doc := map[string]any{"log-level": "debug", "tailnet": cli, "dns": map[string]any{"enable": true, "listen": addr, "nameserver": []string{"tailscale://" + cli.Name}, "default-nameserver": []string{"127.0.0.1"}, "proxy-server-nameserver": []string{bootstrap.LocalAddr().String()}}}
		data, _ := json.Marshal(doc)
		file := filepath.Join(home, "config.json")
		if err = os.WriteFile(file, data, 0600); err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command("/test/mihomo", "-service", "-d", home, "-f", file)
		var logs bytes.Buffer
		cmd.Stdout = &logs
		cmd.Stderr = &logs
		if err = cmd.Start(); err != nil {
			t.Fatal(err)
		}
		stopped := false
		defer func() {
			if !stopped {
				cmd.Process.Kill()
				cmd.Wait()
			}
		}()
		q := new(D.Msg)
		q.SetQuestion("probe-peer.probe.ts.net.", D.TypeA)
		client := &D.Client{Timeout: time.Second}
		ready := false
		for deadline := time.Now().Add(20 * time.Second); time.Now().Before(deadline); {
			response, _, err := client.Exchange(q, addr)
			if err == nil && len(response.Answer) > 0 {
				ready = true
				break
			}
			time.Sleep(100 * time.Millisecond)
		}
		if !ready {
			cmd.Process.Kill()
			cmd.Wait()
			stopped = true
			t.Fatalf("shipping DNS not ready: %s", logs.String())
		}
		q.SetQuestion("native-cli.probe.ts.net.", D.TypeA)
		response, _, err := client.Exchange(q, addr)
		if err != nil || len(response.Answer) == 0 {
			t.Fatalf("shipping node DNS: %v %v", response, err)
		}
		cliIP := netip.MustParseAddr(response.Answer[0].(*D.A).A.String())
		for _, kind := range []tailcfg.PingType{tailcfg.PingTSMP, tailcfg.PingICMP} {
			// DNS can arrive before the peer map and WireGuard handshake.
			deadline := time.Now().Add(20 * time.Second)
			for {
				pingCtx, cancel := context.WithTimeout(ctx, time.Second)
				result, err := pc.Ping(pingCtx, cliIP, kind)
				cancel()
				if err == nil && result.Err == "" {
					break
				}
				if time.Now().After(deadline) || ctx.Err() != nil {
					cmd.Process.Kill()
					cmd.Wait()
					stopped = true
					t.Fatalf("shipping %s: %v %v\n%s", kind, result, err, logs.String())
				}
				time.Sleep(100 * time.Millisecond)
			}
		}
		cmd.Process.Kill()
		cmd.Wait()
		stopped = true
		for i := 0; i < 2; i++ {
			out, err := exec.Command("/test/mihomo", "-cleanup", "-d", home, "-f", file).CombinedOutput()
			if err != nil {
				t.Fatalf("crash cleanup: %v %s", err, out)
			}
		}
		rules, err := exec.Command("ip", "rule").Output()
		if err != nil {
			t.Fatal(err)
		}
		for _, priority := range []string{"5210:", "5230:", "5250:", "5270:"} {
			if bytes.Contains(rules, []byte(priority)) {
				t.Fatalf("stale tailnet rule: %s", rules)
			}
		}
		cmd = exec.Command("/test/mihomo", "-service", "-d", home, "-f", file)
		cmd.Stdout, cmd.Stderr = &logs, &logs
		if err = cmd.Start(); err != nil {
			t.Fatal(err)
		}
		stopped = false
		ready = false
		for deadline := time.Now().Add(20 * time.Second); time.Now().Before(deadline); {
			response, _, err = client.Exchange(q, addr)
			if err == nil && len(response.Answer) > 0 {
				ready = response.Answer[0].(*D.A).A.String() == cliIP.String()
				break
			}
			time.Sleep(100 * time.Millisecond)
		}
		if !ready {
			t.Fatal("shipping restart did not retain identity")
		}
		cmd.Process.Signal(syscall.SIGTERM)
		err = cmd.Wait()
		stopped = true
		if err != nil {
			t.Fatalf("shutdown: %v %s", err, logs.String())
		}
		if _, err = net.InterfaceByName(cli.Interface); err == nil {
			t.Fatal("shipping TUN leaked")
		}
	})

	t.Run("restart_identity_cleanup", func(t *testing.T) {
		key := status.Self.PublicKey
		gateway.Close()
		gateway.Close()
		if _, err := net.InterfaceByName(cfg.Interface); err == nil {
			t.Fatal("TUN remains after close")
		}
		again, err := Start(cfg)
		if err != nil {
			t.Fatal(err)
		}
		defer again.Close()
		until := time.Now().Add(20 * time.Second)
		for again.backend.State() != ipn.Running {
			if time.Now().After(until) {
				t.Fatal("restart not running")
			}
			time.Sleep(50 * time.Millisecond)
		}
		if again.backend.Status().Self.PublicKey != key {
			t.Fatal("node identity changed")
		}
		b, err := exec.Command("ip", "route", "show", "table", "52").CombinedOutput()
		if err != nil {
			t.Fatalf("routes: %s %v", b, err)
		}
		t.Logf("native table 52: %s", b)
	})

}
