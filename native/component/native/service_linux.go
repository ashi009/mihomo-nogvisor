//go:build linux

package native

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	LC "github.com/metacubex/mihomo/listener/config"
	"github.com/metacubex/mihomo/log"
	"github.com/metacubex/nftables"
	"github.com/sagernet/netlink"
	"golang.org/x/sys/unix"
	"gopkg.in/yaml.v3"
	"tailscale.com/wgengine/router"
	_ "tailscale.com/wgengine/router/osrouter"
)

// Lock is shared by supervised startup and offline cleanup. Cleanup must never
// remove a running instance's routes. The lock lasts for the process lifetime.
func Lock(home string) (*os.File, error) {
	if err := os.MkdirAll(home, 0700); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(home, ".service.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = unix.Flock(int(f.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
		f.Close()
		return nil, fmt.Errorf("native service is still running: %w", err)
	}
	return f, nil
}

// Cleanup uses the validated running config, not a possibly invalid new config.
// It is idempotent and is also run before respawn following SIGKILL or a panic.
func Cleanup(path string) error {
	var cfg struct {
		Tun     LC.Tun `yaml:"tun"`
		Tailnet struct {
			Enable    bool   `yaml:"enable"`
			Interface string `yaml:"interface"`
		} `yaml:"tailnet"`
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if err = yaml.Unmarshal(b, &cfg); err != nil {
		return err
	}
	var errs []error
	add := func(err error) {
		if err != nil && !errors.Is(err, unix.ENOENT) && !errors.Is(err, unix.ESRCH) && !errors.Is(err, unix.ENODEV) {
			errs = append(errs, err)
		}
	}
	if cfg.Tun.CapturePolicy != nil {
		if cfg.Tun.IPRoute2RuleIndex <= 0 || cfg.Tun.IPRoute2TableIndex <= 0 || cfg.Tun.Device == "" {
			return errors.New("cleanup requires explicit capture rule/table indices and device")
		}
		nft, err := nftables.New()
		if err != nil {
			return err
		}
		tables, err := nft.ListTables()
		add(err)
		for _, t := range tables {
			if t.Name == "mihomo" && t.Family == nftables.TableFamilyINet {
				nft.DelTable(t)
				add(nft.Flush())
			}
		}
		nft.CloseLasting()
		rules, err := netlink.RuleList(unix.AF_INET)
		add(err)
		for _, rule := range rules {
			if rule.Priority >= cfg.Tun.IPRoute2RuleIndex && rule.Priority <= cfg.Tun.IPRoute2RuleIndex+2 {
				r := netlink.NewRule()
				r.Family, r.Priority = rule.Family, rule.Priority
				if err := netlink.RuleDel(r); err != nil {
					add(fmt.Errorf("delete capture rule %d: %w", rule.Priority, err))
				}
			}
		}
		if link, err := netlink.LinkByName(cfg.Tun.Device); err == nil {
			add(netlink.LinkDel(link))
		}
		include := "/etc/nftables.d/0-mihomo-auto-redirect.nft"
		if err := os.Remove(include); err == nil {
			if fw4, err := exec.LookPath("fw4"); err == nil {
				out, err := exec.Command(fw4, "reload").CombinedOutput()
				if err != nil {
					add(fmt.Errorf("reload fw4: %w: %s", err, out))
				}
			}
		} else if !os.IsNotExist(err) {
			add(err)
		}
	}
	if cfg.Tailnet.Enable {
		name := cfg.Tailnet.Interface
		if name == "" {
			name = "tailscale0"
		}
		router.CleanUp(func(f string, a ...any) { log.Debugln("[Native cleanup] "+f, a...) }, nil, name)
		// Upstream cleanup does not remove the policy routing rules.
		// Linux deletes interface routes when the TUN closes; remove its exact
		// standard policy rules too, without touching other owners' priorities.
		rules, err := netlink.RuleList(netlink.FAMILY_ALL)
		add(err)
		for _, r := range rules {
			owned := r.Priority == 5270 && r.Table == 52 || r.Mark == 0x80000 && r.Mask == 0xff0000 && (r.Priority == 5210 || r.Priority == 5230 || r.Priority == 5250)
			if owned {
				rule := netlink.NewRule()
				rule.Family, rule.Priority = r.Family, r.Priority
				rule.Mark, rule.Mask, rule.Table = r.Mark, r.Mask, r.Table
				// RuleList does not preserve the action in this netlink fork.
				// 5250 is unreachable, not a lookup in its decoded table 0.
				if r.Priority == 5250 {
					rule.Table = -1
				}
				if err := netlink.RuleDel(rule); err != nil {
					add(fmt.Errorf("delete tailnet rule %d: %w", r.Priority, err))
				}
			}
		}
		if link, err := netlink.LinkByName(name); err == nil {
			add(netlink.LinkDel(link))
		}
	}
	return errors.Join(errs...)
}
