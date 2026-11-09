//go:build linux

package tun

import (
	"net/netip"

	"github.com/metacubex/nftables"
	"github.com/metacubex/nftables/binaryutil"
	"github.com/metacubex/nftables/expr"
	"golang.org/x/sys/unix"
)

// These chains run before both first-packet selection and conntrack mark
// restoration. Exempt traffic must not inherit a capture mark after reload.
func (r *autoRedirect) captureExclusions(nft *nftables.Conn, table *nftables.Table, chain *nftables.Chain) {
	if r.tunOptions.CapturePolicy == nil {
		return
	}
	nft.AddRule(&nftables.Rule{Table: table, Chain: chain, Exprs: []expr.Any{&expr.Verdict{Kind: expr.VerdictJump, Chain: "capture_select"}}})
}

func (r *autoRedirect) setupCapturePolicy(nft *nftables.Conn, table *nftables.Table) error {
	p := r.tunOptions.CapturePolicy
	if p == nil {
		return nil
	}
	add := func(c *nftables.Chain, matches []expr.Any, actions ...expr.Any) {
		nft.AddRule(&nftables.Rule{Table: table, Chain: c, Exprs: append(matches, append([]expr.Any{&expr.Counter{}}, actions...)...)})
	}
	// ACCEPT terminates this base-chain traversal without selecting the packet.
	// RETURN would resume the caller and accidentally capture an exception.
	bypass := &expr.Verdict{Kind: expr.VerdictAccept}
	meta := func(key expr.MetaKey, data []byte, invert bool) []expr.Any {
		op := expr.CmpOpEq
		if invert {
			op = expr.CmpOpNeq
		}
		return []expr.Any{&expr.Meta{Key: key, Register: 1}, &expr.Cmp{Op: op, Register: 1, Data: data}}
	}
	proto := func(n byte) []expr.Any { return meta(expr.MetaKeyL4PROTO, []byte{n}, false) }
	port := func(n uint16) []expr.Any {
		return []expr.Any{&expr.Payload{DestRegister: 1, Base: expr.PayloadBaseTransportHeader, Offset: 2, Len: 2}, &expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: binaryutil.BigEndian.PutUint16(n)}}
	}
	policy := nft.AddChain(&nftables.Chain{Table: table, Name: "capture_select"})
	dns := nft.AddChain(&nftables.Chain{Table: table, Name: "capture_dns", Hooknum: nftables.ChainHookPrerouting, Priority: nftables.ChainPriorityRef(*nftables.ChainPriorityNATDest - 1), Type: nftables.ChainTypeNAT})
	for _, c := range []*nftables.Chain{policy, dns} {
		add(c, meta(expr.MetaKeyMARK, binaryutil.NativeEndian.PutUint32(p.BypassMark), false), bypass)
		gids := p.BypassGIDs
		if c == dns {
			gids = p.DNSBypassGIDs
		}
		for _, gid := range gids {
			add(c, meta(expr.MetaKeySKGID, binaryutil.NativeEndian.PutUint32(gid), false), bypass)
		}
		add(c, meta(expr.MetaKeyIIFNAME, nftablesIfname(r.tunOptions.Name), false), bypass)
	}
	prefixExpr := func(prefix netip.Prefix, source, invert bool) []expr.Any {
		family, offset, length := byte(nftables.TableFamilyIPv4), uint32(16), uint32(4)
		if !prefix.Addr().Is4() {
			family, offset, length = byte(nftables.TableFamilyIPv6), 24, 16
		}
		if source {
			if length == 4 {
				offset = 12
			} else {
				offset = 8
			}
		}
		mask := make([]byte, length)
		for bit := 0; bit < prefix.Bits(); bit++ {
			mask[bit/8] |= 1 << (7 - bit%8)
		}
		op := expr.CmpOpEq
		if invert {
			op = expr.CmpOpNeq
		}
		result := meta(expr.MetaKeyNFPROTO, []byte{family}, false)
		return append(result, &expr.Payload{DestRegister: 1, Base: expr.PayloadBaseNetworkHeader, Offset: offset, Len: length},
			&expr.Bitwise{SourceRegister: 1, DestRegister: 1, Len: length, Mask: mask, Xor: make([]byte, length)},
			&expr.Cmp{Op: op, Register: 1, Data: prefix.Addr().AsSlice()})
	}
	for _, prefix := range append(append([]netip.Prefix{}, p.Sources...), p.DNS6Sources...) {
		for _, protocol := range []byte{unix.IPPROTO_TCP, unix.IPPROTO_UDP} {
			matches := append(prefixExpr(prefix, true, false), proto(protocol)...)
			matches = append(matches, port(53)...)
			add(dns, matches, &expr.Immediate{Register: 1, Data: binaryutil.BigEndian.PutUint16(p.DNSPort)}, &expr.Redir{RegisterProtoMin: 1, Flags: unix.NF_NAT_RANGE_PROTO_SPECIFIED})
		}
	}
	add(policy, meta(expr.MetaKeyNFPROTO, []byte{byte(nftables.TableFamilyIPv4)}, true), bypass)
	var outsideSources []expr.Any
	for _, prefix := range p.Sources {
		outsideSources = append(outsideSources, prefixExpr(prefix, true, true)...)
	}
	add(policy, outsideSources, bypass)
	for _, prefix := range r.tunOptions.Inet4RouteExcludeAddress {
		add(policy, prefixExpr(prefix, false, false), bypass)
	}
	for _, protocol := range []byte{unix.IPPROTO_TCP, unix.IPPROTO_UDP} {
		add(policy, append(proto(protocol), port(53)...), bypass)
	}
	for _, n := range p.UDPBypass {
		add(policy, append(proto(unix.IPPROTO_UDP), port(n)...), bypass)
	}
	// Reuse the provider-backed set, including live updates. This must run
	// before UDP conntrack marks are restored, not only in the NAT chain.
	// Fake addresses still need Mihomo even if a provider includes them.
	if len(*r.routeExcludeAddressSet) > 0 {
		matches := prefixExpr(p.FakeIP, false, true)
		matches = append(matches, nftablesCreateDestinationIPSetExprs(3, "inet4_route_exclude_address_set", nftables.TableFamilyIPv4, false)...)
		add(policy, matches, bypass)
	}
	// Only TCP/UDP can reach the transport-port expression below.
	transport := nft.AddChain(&nftables.Chain{Table: table, Name: "capture_ports"})
	for _, protocol := range []byte{unix.IPPROTO_TCP, unix.IPPROTO_UDP} {
		add(policy, proto(protocol), &expr.Verdict{Kind: expr.VerdictGoto, Chain: transport.Name})
	}
	add(policy, nil, bypass)
	add(transport, prefixExpr(p.FakeIP, false, false), &expr.Verdict{Kind: expr.VerdictReturn})
	for _, n := range p.Ports {
		add(transport, port(n), &expr.Verdict{Kind: expr.VerdictReturn})
	}
	add(transport, nil, bypass)
	return nil
}
