package tun

import (
	"fmt"
	"net"
	"net/netip"
	"slices"
)

// InterfacePrefixes returns the configured IPv4 networks of explicitly chosen
// LAN interfaces. Never infer LAN scope from default routes or overlay peers.
func InterfacePrefixes(names []string) ([]netip.Prefix, error) {
	var prefixes []netip.Prefix
	for _, name := range names {
		iface, err := net.InterfaceByName(name)
		if err != nil {
			return nil, fmt.Errorf("LAN interface %q: %w", name, err)
		}
		addresses, err := iface.Addrs()
		if err != nil {
			return nil, fmt.Errorf("LAN interface %q addresses: %w", name, err)
		}
		found := false
		for _, address := range addresses {
			prefix, err := netip.ParsePrefix(address.String())
			if err != nil || !prefix.Addr().Is4() || !prefix.Addr().IsGlobalUnicast() || prefix.Bits() == 0 {
				continue
			}
			found = true
			prefix = prefix.Masked()
			if !slices.Contains(prefixes, prefix) {
				prefixes = append(prefixes, prefix)
			}
		}
		if !found {
			return nil, fmt.Errorf("LAN interface %q has no usable IPv4 prefix", name)
		}
	}
	slices.SortFunc(prefixes, func(a, b netip.Prefix) int {
		if order := a.Addr().Compare(b.Addr()); order != 0 {
			return order
		}
		return a.Bits() - b.Bits()
	})
	return prefixes, nil
}
