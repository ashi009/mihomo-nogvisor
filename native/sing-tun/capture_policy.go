package tun

import (
	"fmt"
	"net/netip"
	"slices"
)

// CapturePolicy selects forwarded IPv4 TCP/UDP flows. DNS has its own scope
// and is redirected before destination exclusions. A nil policy is upstream
// behavior; an enabled policy never captures router-originated traffic.
type CapturePolicy struct {
	SourceInterfaces []string       `yaml:"source-interfaces" json:"source-interfaces"`
	Sources          []netip.Prefix `yaml:"sources" json:"sources"`
	DNS6Sources      []netip.Prefix `yaml:"dns6-sources" json:"dns6-sources"`
	FakeIP           netip.Prefix   `yaml:"fake-ip" json:"fake-ip"`
	Ports            []uint16       `yaml:"ports" json:"ports"`
	UDPBypass        []uint16       `yaml:"udp-bypass" json:"udp-bypass"`
	DNSPort          uint16         `yaml:"dns-port" json:"dns-port"`
	BypassMark       uint32         `yaml:"bypass-mark" json:"bypass-mark"`
	BypassGIDs       []uint32       `yaml:"bypass-gids" json:"bypass-gids"`
	DNSBypassGIDs    []uint32       `yaml:"dns-bypass-gids" json:"dns-bypass-gids"`
}

func (p *CapturePolicy) Validate() error {
	if p == nil {
		return nil
	}
	prefixes, err := InterfacePrefixes(p.SourceInterfaces)
	if err != nil {
		return err
	}
	for _, prefix := range prefixes {
		if !slices.Contains(p.Sources, prefix) {
			p.Sources = append(p.Sources, prefix)
		}
	}
	if len(p.Sources) == 0 || len(p.Ports) == 0 || !p.FakeIP.IsValid() || !p.FakeIP.Addr().Is4() || p.FakeIP != p.FakeIP.Masked() || p.DNSPort == 0 || p.BypassMark == 0 {
		return fmt.Errorf("capture-policy needs sources, ports, canonical IPv4 fake-ip, dns-port and bypass-mark")
	}
	for _, group := range []struct {
		prefixes []netip.Prefix
		ipv4     bool
	}{{p.Sources, true}, {p.DNS6Sources, false}} {
		for _, prefix := range group.prefixes {
			if !prefix.IsValid() || prefix != prefix.Masked() || prefix.Addr().Is4() != group.ipv4 {
				return fmt.Errorf("invalid capture-policy source %s", prefix)
			}
		}
	}
	for _, ports := range [][]uint16{p.Ports, p.UDPBypass} {
		for _, port := range ports {
			if port == 0 {
				return fmt.Errorf("zero capture-policy port")
			}
		}
	}
	return nil
}
