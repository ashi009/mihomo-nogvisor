//go:build linux && with_gvisor

package tailnet

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"testing"
	"time"

	C "github.com/metacubex/mihomo/constant"
)

// The packet harness supplies a veth ingress instead of a real encrypted peer.
// Rules come from the same installer used before the native TUN is opened.
func TestLANOnlyFirewallFixture(t *testing.T) {
	home := os.Getenv("MIHOMO_FIREWALL_FIXTURE")
	if home == "" {
		t.Skip("started by capture.py")
	}
	C.SetHomeDir(home)
	var input struct {
		MixedPort  int    `json:"mixed-port"`
		Controller string `json:"external-controller"`
		DNS        struct {
			Listen string `json:"listen"`
		} `json:"dns"`
	}
	data, err := os.ReadFile(filepath.Join(home, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(data, &input); err != nil {
		t.Fatal(err)
	}
	cfg, err := ProtectListeners(Config{Enable: true, ProtectListeners: true, Interface: "tailscale0"}, []int{input.MixedPort}, nil, input.Controller, input.DNS.Listen)
	if err != nil {
		t.Fatal(err)
	}
	cfg, err = Normalize(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if err = installListenerFirewall(cfg); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if err := CleanupListenerFirewall(); err != nil {
			t.Error(err)
		}
	}()
	if err = os.WriteFile(filepath.Join(home, "firewall-ready"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	for {
		if _, err := os.Stat(filepath.Join(home, "firewall-stop")); err == nil {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func TestProtectedListenerPorts(t *testing.T) {
	cfg, err := ProtectListeners(Config{Enable: true, ProtectListeners: true}, []int{7890}, []map[string]any{{"port": 1234}}, "0.0.0.0:9090", "[::]:1053")
	if err != nil {
		t.Fatal(err)
	}
	want := []uint16{1053, 1234, 7890, 9090}
	if !slices.Equal(cfg.ProtectedPorts, want) {
		t.Fatalf("got %v, want %v", cfg.ProtectedPorts, want)
	}
	if _, err := ProtectListeners(Config{Enable: true, ProtectListeners: true}, nil, []map[string]any{{"port": "dynamic"}}); err == nil {
		t.Fatal("accepted nonnumeric listener port")
	}
}
