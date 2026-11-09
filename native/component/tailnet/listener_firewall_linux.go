//go:build linux

package tailnet

import (
	"fmt"
	"net"
	"os/exec"
	"slices"
	"strconv"
	"strings"

	"github.com/metacubex/nftables"
)

const firewallTable = "mihomo_listeners"

// ProtectListeners derives the router-local ports from the Mihomo configuration,
// so changing a listener cannot leave a stale firewall allowlist behind.
func ProtectListeners(c Config, ports []int, listeners []map[string]any, addresses ...string) (Config, error) {
	if !c.Enable || !c.ProtectListeners {
		return c, nil
	}
	c.ProtectedPorts = nil
	for _, listener := range listeners {
		value, ok := listener["port"]
		if !ok {
			return c, fmt.Errorf("tailnet protected listener needs a fixed port")
		}
		port, err := strconv.Atoi(fmt.Sprint(value))
		if err != nil || port < 1 || port > 65535 {
			return c, fmt.Errorf("invalid protected listener port %v", value)
		}
		ports = append(ports, port)
	}
	for _, address := range addresses {
		if address == "" {
			continue
		}
		_, value, err := net.SplitHostPort(address)
		if err != nil {
			return c, fmt.Errorf("tailnet protected listener %q: %w", address, err)
		}
		port, err := strconv.Atoi(value)
		if err != nil || port < 1 || port > 65535 {
			return c, fmt.Errorf("tailnet protected listener %q needs a fixed port", address)
		}
		ports = append(ports, port)
	}
	for _, port := range ports {
		if port < 0 || port > 65535 {
			return c, fmt.Errorf("invalid protected port %d", port)
		}
		if port > 0 && !slices.Contains(c.ProtectedPorts, uint16(port)) {
			c.ProtectedPorts = append(c.ProtectedPorts, uint16(port))
		}
	}
	slices.Sort(c.ProtectedPorts)
	return c, nil
}

func nftCommand(script string) error {
	command := exec.Command("nft", "-f", "-")
	command.Stdin = strings.NewReader(script)
	if output, err := command.CombinedOutput(); err != nil {
		return fmt.Errorf("tailnet nftables: %w: %s", err, output)
	}
	return nil
}

func hasTable(name string) (bool, error) {
	conn, err := nftables.New()
	if err != nil {
		return false, err
	}
	defer conn.CloseLasting()
	tables, err := conn.ListTables()
	if err != nil {
		return false, err
	}
	for _, table := range tables {
		if table.Name == name && table.Family == nftables.TableFamilyINet {
			return true, nil
		}
	}
	return false, nil
}

// A separate input hook survives fw4 reloads and only restricts router-local listeners.
func installListenerFirewall(c Config) error {
	exists, err := hasTable(firewallTable)
	if err != nil {
		return err
	}
	script := ""
	if exists {
		script = "delete table inet " + firewallTable + "\n"
	}
	script += "table inet " + firewallTable + " {\nchain input { type filter hook input priority -10; policy accept;\n"
	for _, p := range c.ProtectedPorts {
		for _, proto := range []string{"tcp", "udp"} {
			script += fmt.Sprintf("iifname %s %s dport %d counter drop\n", strconv.Quote(c.Interface), proto, p)
		}
	}
	return nftCommand(script + "}\n}\n")
}

func CleanupListenerFirewall() error {
	exists, err := hasTable(firewallTable)
	if err != nil || !exists {
		return err
	}
	return nftCommand("delete table inet " + firewallTable + "\n")
}
