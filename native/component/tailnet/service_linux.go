//go:build linux

package tailnet

import (
	"context"
	"errors"
	"fmt"
	"github.com/metacubex/mihomo/component/resolver"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/log"
	"net/netip"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"

	mdns "github.com/metacubex/mihomo/dns"
	forktun "github.com/metacubex/tailscale-wireguard-go/tun"
	"github.com/metacubex/tailscale/control/controlclient"
	"github.com/metacubex/tailscale/envknob"
	"github.com/metacubex/tailscale/ipn"
	"github.com/metacubex/tailscale/ipn/ipnlocal"
	"github.com/metacubex/tailscale/ipn/store"
	"github.com/metacubex/tailscale/net/netmon"
	"github.com/metacubex/tailscale/net/tsdial"
	"github.com/metacubex/tailscale/tsd"
	"github.com/metacubex/tailscale/types/logid"
	"github.com/metacubex/tailscale/util/eventbus"
	"github.com/metacubex/tailscale/wgengine"
	"github.com/metacubex/tailscale/wgengine/router"
	_ "github.com/metacubex/tailscale/wgengine/router/osrouter"
	D "github.com/miekg/dns"
	nativetun "github.com/tailscale/wireguard-go/tun"
	"golang.org/x/net/dns/dnsmessage"
	"golang.org/x/sys/unix"
)

type Config struct {
	FirewallMode    string         `yaml:"firewall-mode" json:"firewall-mode"`
	Enable          bool           `yaml:"enable" json:"enable"`
	Name            string         `yaml:"name" json:"name"`
	Hostname        string         `yaml:"hostname" json:"hostname"`
	Interface       string         `yaml:"interface" json:"interface"`
	StateDir        string         `yaml:"state-dir" json:"state-dir"`
	ControlURL      string         `yaml:"control-url" json:"control-url"`
	AuthKeyFile     string         `yaml:"auth-key-file" json:"auth-key-file"`
	AdvertiseRoutes []netip.Prefix `yaml:"advertise-routes" json:"advertise-routes"`
	AcceptRoutes    bool           `yaml:"accept-routes" json:"accept-routes"`
	Port            uint16         `yaml:"port" json:"port"`
}

var mu sync.Mutex
var active *Service

func Normalize(c Config) (Config, error) {
	if !c.Enable {
		return Config{}, nil
	}
	if c.FirewallMode == "" {
		c.FirewallMode = "nftables"
	}
	if c.FirewallMode != "nftables" && c.FirewallMode != "iptables" && c.FirewallMode != "auto" {
		return c, errors.New("invalid tailnet firewall-mode")
	}
	if c.Name == "" {
		c.Name = "tailnet"
	}
	if c.Interface == "" {
		c.Interface = "tailscale0"
	}
	if c.StateDir == "" {
		c.StateDir = "tailnet"
	}
	if c.Hostname == "" {
		return c, errors.New("tailnet hostname is required")
	}
	if len(c.Interface) > 15 || strings.ContainsAny(c.Interface, " /\\") {
		return c, errors.New("invalid tailnet interface")
	}
	c.StateDir = C.Path.Resolve(c.StateDir)
	if !C.Path.IsSafePath(c.StateDir) {
		return c, errors.New("tailnet state-dir outside home")
	}
	for _, p := range c.AdvertiseRoutes {
		if !p.IsValid() || p != p.Masked() || p.Bits() == 0 {
			return c, errors.New("advertise-routes requires canonical non-default prefixes")
		}
	}
	if c.AuthKeyFile != "" {
		c.AuthKeyFile = C.Path.Resolve(c.AuthKeyFile)
		if !C.Path.IsSafePath(c.AuthKeyFile) {
			return c, errors.New("auth-key-file outside home")
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if active != nil && !reflect.DeepEqual(active.config, c) {
		return c, errors.New("tailnet configuration changed: restart required")
	}
	return c, nil
}
func Apply(c Config) error {
	mu.Lock()
	defer mu.Unlock()
	if !c.Enable {
		if active != nil {
			active.Close()
			active = nil
		}
		return nil
	}
	if active != nil {
		if reflect.DeepEqual(active.config, c) {
			return nil
		}
		return errors.New("tailnet configuration changed: restart required")
	}
	var err error
	active, err = Start(c)
	return err
}
func Shutdown() {
	mu.Lock()
	defer mu.Unlock()
	if active != nil {
		active.Close()
		active = nil
	}
}

type Service struct {
	config  Config
	backend *ipnlocal.LocalBackend
	cleanup []func()
	once    sync.Once
}

func (s *Service) Close() {
	s.once.Do(func() {
		for i := len(s.cleanup) - 1; i >= 0; i-- {
			s.cleanup[i]()
		}
	})
}
func Start(c Config) (service *Service, retErr error) {
	ctx := context.Background()
	envknob.SetNoLogsNoSupport()
	service = &Service{config: c}
	owned := service
	defer func() {
		if retErr != nil {
			owned.Close()
			service = nil
		}
	}()
	add := func(f func()) { service.cleanup = append(service.cleanup, f) }
	if err := os.MkdirAll(c.StateDir, 0700); err != nil {
		return nil, err
	}
	lock, err := os.OpenFile(filepath.Join(c.StateDir, "service.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	add(func() { lock.Close() })
	if err = unix.Flock(int(lock.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
		return nil, fmt.Errorf("tailnet state already in use: %w", err)
	}
	auth := ""
	if c.AuthKeyFile != "" {
		b, err := os.ReadFile(c.AuthKeyFile)
		if err != nil {
			return nil, err
		}
		auth = strings.TrimSpace(string(b))
	}

	logf := func(f string, a ...any) { log.Debugln("[Tailnet] "+f, a...) }
	sys := tsd.NewSystemWithBus(eventbus.NewWithOptions(eventbus.BusOptions{Logf: logf}))
	add(sys.Bus.Get().Close)
	nm, err := netmon.New(sys.Bus.Get(), logf)
	if err != nil {
		return nil, err
	}
	add(func() { nm.Close() })
	sys.Set(nm)
	dialer := &tsdial.Dialer{Logf: logf}
	dialer.LookupHook = func(ctx context.Context, host string) ([]netip.Addr, error) {
		if ip, err := netip.ParseAddr(host); err == nil {
			return []netip.Addr{ip}, nil
		}
		if resolver.ProxyServerHostResolver == nil {
			return nil, errors.New("tailnet bootstrap resolver not ready")
		}
		return resolver.LookupIPWithResolver(ctx, host, resolver.ProxyServerHostResolver)
	}
	sys.LookupHook = dialer.LookupHook
	dialer.SetBus(sys.Bus.Get())
	sys.Set(dialer)
	add(func() { dialer.Close() })
	native, err := nativetun.CreateTUN(c.Interface, 1280)
	if err != nil {
		return nil, err
	}
	dev := &nativeTUN{Device: native, events: make(chan forktun.Event, 16), done: make(chan struct{})}
	go func() {
		defer close(dev.events)
		for event := range native.Events() {
			select {
			case dev.events <- forktun.Event(event):
			case <-dev.done:
				return
			}
		}
	}()
	r, err := router.New(logf, dev, nm, sys.HealthTracker.Get(), sys.Bus.Get())
	if err != nil {
		dev.Close()
		return nil, err
	}
	sys.Set(r)
	eng, err := wgengine.NewUserspaceEngine(logf, wgengine.Config{
		Tun: dev, Router: r, ListenPort: c.Port, NetMon: nm, Dialer: dialer,
		SetSubsystem: sys.Set, ControlKnobs: sys.ControlKnobs(),
		HealthTracker: sys.HealthTracker.Get(), Metrics: sys.UserMetricsRegistry(), EventBus: sys.Bus.Get(), LookupHook: dialer.LookupHook,
	})
	if err != nil {
		r.Close()
		dev.Close()
		return nil, err
	}
	sys.Set(eng)
	sys.NetstackRouter.Set(false)
	root := c.StateDir
	st, err := store.New(logf, filepath.Join(root, "tailscaled.state"))
	if err != nil {
		eng.Close()
		return nil, err
	}
	sys.Set(st)
	sys.Tun.Get().Start()
	backend, err := ipnlocal.NewLocalBackend(logf, logid.PublicID{}, sys, controlclient.LoginDefault)
	if err != nil {
		eng.Close()
		return nil, err
	}
	add(backend.Shutdown)
	service.backend = backend
	backend.SetVarRoot(root)
	prefs := ipn.NewPrefs()
	prefs.Hostname = c.Hostname
	if c.ControlURL != "" {
		prefs.ControlURL = c.ControlURL
	}
	prefs.NetfilterKind = c.FirewallMode
	prefs.WantRunning = true
	prefs.RouteAll = c.AcceptRoutes
	prefs.AdvertiseRoutes = c.AdvertiseRoutes
	if err = backend.Start(ipn.Options{UpdatePrefs: prefs, AuthKey: auth}); err != nil {
		return nil, err
	}
	backend.SetNotifyCallback(func(n ipn.Notify) {
		if n.BrowseToURL != nil {
			log.Warnln("[Tailnet] login: %s", *n.BrowseToURL)
		}
		if n.ErrMessage != nil {
			log.Errorln("[Tailnet] %s", *n.ErrMessage)
		}
	})
	if backend.State() == ipn.NeedsLogin {
		if err := backend.StartLoginInteractive(ctx); err != nil {
			return nil, err
		}
	}
	unregister := mdns.RegisterTailscaleDnsClient(c.Name, nativeDNS{backend, c.Name})
	add(unregister)
	return service, nil
}

type nativeDNS struct {
	backend *ipnlocal.LocalBackend
	name    string
}

func (d nativeDNS) Address() string  { return "tailscale://" + d.name }
func (d nativeDNS) ResetConnection() {}
func (d nativeDNS) ExchangeContext(ctx context.Context, q *D.Msg) (*D.Msg, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if len(q.Question) != 1 {
		return nil, fmt.Errorf("one DNS question required")
	}
	b, _, err := d.backend.QueryDNS(q.Question[0].Name, dnsmessage.Type(q.Question[0].Qtype))
	if err != nil {
		return nil, err
	}
	response := new(D.Msg)
	if err = response.Unpack(b); err != nil {
		return nil, err
	}
	response.Id = q.Id
	return response, nil
}

type nativeTUN struct {
	nativetun.Device
	events    chan forktun.Event
	done      chan struct{}
	closeOnce sync.Once
	closeErr  error
}

func (d *nativeTUN) Events() <-chan forktun.Event { return d.events }

func (d *nativeTUN) Close() error {
	d.closeOnce.Do(func() { close(d.done); d.closeErr = d.Device.Close() })
	return d.closeErr
}
