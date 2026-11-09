#!/usr/bin/env python3
"""Exercise the shipping binary through real forwarded TCP, UDP and DNS."""
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess as sp
import sys
import time

def run(*args, **kwargs):
    result=sp.run(args, text=True, stdout=sp.PIPE, stderr=sp.PIPE, **kwargs)
    if result.returncode:
        print(result.stdout+result.stderr,file=sys.stderr)
        result.check_returncode()
    return result.stdout

if len(sys.argv)>1 and sys.argv[1]=='echo':
    import threading
    def serve(addr, port, udp):
        s=socket.socket(socket.AF_INET6 if ':' in addr else socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        s.bind((addr,port))
        if udp:
            while True:
                data,peer=s.recvfrom(2048)
                if len(sys.argv)>4:assert peer[0]==sys.argv[4],peer
                s.sendto(data,peer)
        else:
            s.listen()
            while True:
                c,peer=s.accept()
                if len(sys.argv)>4:
                    assert peer[0]==sys.argv[4],peer
                    assert c.getsockopt(socket.IPPROTO_TCP,socket.TCP_MAXSEG)<=1240,'MSS not clamped'
                try:c.settimeout(1);c.sendall(c.recv(2048))
                except OSError:pass
                c.close()
    for addr in (sys.argv[2].split(',') if len(sys.argv)>2 else ['198.51.100.2','198.51.100.3','198.51.100.4','192.168.70.2','28.1.1.1','fd77::2']):
        for port in (list(map(int,sys.argv[3].split(','))) if len(sys.argv)>3 else [22,53,80,443,8080,8443,18081]):
            for udp in [False,True]:threading.Thread(target=serve,args=(addr,port,udp),daemon=True).start()
    time.sleep(300)
    sys.exit()

if len(sys.argv)>1 and sys.argv[1]=='connect':
    try:
        socket.create_connection((sys.argv[2],int(sys.argv[3])),timeout=.6).close();print('connected')
    except OSError:print('blocked')
    sys.exit()

if len(sys.argv)>1 and sys.argv[1] in ['probe','flow']:
    _,_,host,port,udp,source=sys.argv
    s=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_DGRAM if udp=='1' else socket.SOCK_STREAM)
    s.settimeout(.6)
    if source!='-':s.bind((source,0))
    s.connect((host,int(port))) if udp=='1' else None
    def probe():
        try:
            if udp!='1':s.connect((host,int(port)))
            s.sendall(b'capture-probe')
            print('echo' if s.recv(64)==b'capture-probe' else 'blocked',flush=True)
        except OSError:print('blocked',flush=True)
    if sys.argv[1]=='flow':
        for _ in sys.stdin:probe()
    else:probe()
    sys.exit()

if len(sys.argv)>1 and sys.argv[1]=='dns':
    host=sys.argv[2];tcp=sys.argv[3]=='tcp'
    q=struct.pack('!6H',1234,0x100,1,0,0,0)+b'\x05probe\x04test\x00'+struct.pack('!2H',1,1)
    s=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)
    s.settimeout(2);s.connect((host,int(sys.argv[4]) if len(sys.argv)>4 else 53))
    s.sendall(struct.pack('!H',len(q))+q if tcp else q)
    answer=s.recv(2048)
    assert socket.inet_aton('192.0.2.42') in answer,answer
    print('dns ok');sys.exit()

def ip(*args):return run('ip',*args)
def ns(name,*args):return run('ip','netns','exec',name,*args)
def check(label,host,port,udp=False,expected='blocked',source='-',namespace='client'):
    args=['python3',__file__,'probe',host,str(port),'1' if udp else '0',source]
    got=(ns(namespace,*args) if namespace else run(*args)).strip()
    assert got==expected,(label,host,port,udp,got,expected)
    print('PASS',label,host,port,'udp' if udp else 'tcp',flush=True)

for name in ['client','target','tailclient']:ip('netns','add',name)
for name,dev,local,remote in [('client','br-lan','10.66.0.1/24','10.66.0.2/24'),('target','wan','203.0.113.1/24','203.0.113.2/24'),('tailclient','tailscale0','100.99.0.1/24','100.99.0.2/24')]:
    ip('link','add',dev,'type','veth','peer','name',dev+'peer')
    ip('link','set',dev+'peer','netns',name)
    ip('addr','add',local,'dev',dev);ip('link','set',dev,'up')
    ns(name,'ip','addr','add',remote,'dev',dev+'peer');ns(name,'ip','link','set',dev+'peer','up');ns(name,'ip','link','set','lo','up')
    ns(name,'ip','route','add','default','via',local.split('/')[0])
ip('link','set','tailscale0','mtu','1280')
ns('tailclient','ip','addr','add','10.66.0.99/32','dev','tailscale0peer')
ip('route','add','10.66.0.99/32','via','100.99.0.2')
ns('client','ip','route','add','10.66.0.99/32','via','10.66.0.1')
ns('client','ip','addr','add','10.67.0.2/24','dev','br-lanpeer')
ip('route','add','10.67.0.0/24','dev','br-lan')
for prefix in ['198.51.100.2/32','198.51.100.3/32','198.51.100.4/32','192.168.70.2/32','28.1.1.1/32']:ns('target','ip','addr','add',prefix,'dev','lo');ip('route','add',prefix,'via','203.0.113.2')
for namespace,device,addr in [(None,'br-lan','fd66::1/64'),('client','br-lanpeer','fd66::2/64'),(None,'tailscale0','fd99::1/64'),('tailclient','tailscale0peer','fd99::2/64'),(None,'wan','fd77::1/64'),('target','wanpeer','fd77::2/64')]:
    args=['ip','-6','addr','add',addr,'dev',device,'nodad'];ns(namespace,*args) if namespace else run(*args)
ns('client','ip','-6','route','add','default','via','fd66::1');ns('target','ip','-6','route','add','default','via','fd77::1')
ns('tailclient','ip','-6','route','add','default','via','fd99::1')
# Use OpenWrt's real UCI/fw4 and the APK helper against a legacy Tailscale zone.
Path('/etc/config/firewall').write_text("""
config defaults
 option input 'REJECT'
 option output 'ACCEPT'
 option forward 'REJECT'
config zone 'lan'
 option name 'lan'
 option device 'br-lan'
 option input 'ACCEPT'
 option output 'ACCEPT'
 option forward 'ACCEPT'
config zone 'wan'
 option name 'wan'
 option device 'wan'
 option input 'REJECT'
 option output 'ACCEPT'
 option forward 'REJECT'
config forwarding 'lan_wan'
 option src 'lan'
 option dest 'wan'
config rule 'ndp'
 option name 'IPv6 neighbour discovery'
 option src '*'
 option family 'ipv6'
 option proto 'icmp'
 option target 'ACCEPT'
config zone
 option name 'tailscale'
 option device 'tailscale0'
 option input 'ACCEPT'
 option output 'ACCEPT'
 option forward 'ACCEPT'
 option masq '1'
 option mtu_fix '1'
config forwarding
 option src 'lan'
 option dest 'tailscale'
config forwarding
 option src 'tailscale'
 option dest 'lan'
""")
Path('/etc/config/network').write_text("""
config interface 'tailscale'
 option proto 'none'
 option device 'tailscale0'
""")
Path('/usr/share/mihomo').mkdir(exist_ok=True)
Path('/usr/share/mihomo/tailnet-firewall.uci').write_text(Path('/package/tailnet-firewall.uci').read_text())
helper=['sh','/package/mihomo-firewall']
run('fw4','start')
run(*helper,'apply')
state=run('uci','export','firewall')
assert "option name 'tailscale'" not in state and "option dest 'tailscale'" not in state,state
assert 'tailscale' not in run('uci','export','network')
run(*helper,'apply');assert state==run('uci','export','firewall')
run('uci','set','firewall.pending=rule')
failed=sp.run(helper+['apply'],stdout=sp.PIPE,stderr=sp.PIPE,text=True)
assert failed.returncode!=0 and 'Uncommitted UCI changes' in failed.stderr
assert 'firewall.pending' in run('uci','changes','firewall')
run('uci','revert','firewall')
assert state==run('uci','export','firewall')
print('PASS package adopts legacy UCI sections, reapplies idempotently and preserves pending edits',flush=True)
echo=sp.Popen(['ip','netns','exec','target','python3',__file__,'echo'])
lan_echo=sp.Popen(['ip','netns','exec','client','python3',__file__,'echo','10.66.0.2','53,80,7890'])
tail_echo=sp.Popen(['ip','netns','exec','tailclient','python3',__file__,'echo','100.99.0.2','80','100.99.0.1'])
router_echo=sp.Popen(['python3',__file__,'echo','10.66.0.1','18082'])
time.sleep(.3)
# A neighbouring Tailscale rule must survive TUN setup, reconfiguration and stop.
ip('rule','add','priority','5210','fwmark','0x80000/0xff0000','table','main')
ip('rule','add','priority','32768','from','192.0.2.99','table','main')
def check_foreign_rules():
    rules=ip('rule')
    assert '5210:' in rules and '32768:' in rules,rules
home=Path('/tmp/capture');home.mkdir()
config=json.loads(Path('/test/capture.json').read_text());(home/'config.json').write_text(json.dumps(config))
log=(home/'core.log').open('w+')
core=None
flow=None
firewall=None
(home/'cn-ip.yaml').write_text('payload: []\n')
def update_bypass(prefixes):
    (home/'cn-ip.yaml').write_text('payload:\n' + ''.join('  - '+prefix+'\n' for prefix in prefixes))
    run('curl','-fsS','-X','PUT','http://127.0.0.1:19090/providers/rules/cn-ip')
    for _ in range(50):
        state=run('nft','list','set','inet','mihomo','inet4_route_exclude_address_set')
        expected=[prefix.split('/')[0] for prefix in prefixes]
        if all(addr in state for addr in expected) and (prefixes or 'elements' not in state):return
        time.sleep(.1)
    raise AssertionError('provider update did not reach nftables')
def check_cn():
    for udp in [False,True]:check('CN IP bypasses Mihomo REJECT','198.51.100.3',80,udp,'echo')
    check('non-CN still captured','198.51.100.2',80)
    check('fake IP wins over provider overlap','28.1.1.1',18081)
    check('fake UDP wins over provider overlap','28.1.1.1',18081,True)
def check_tailnet():
    for udp in [False,True]:
        for port in [53,80,7890]:check('tailnet reaches LAN unchanged','10.66.0.2',port,udp,'echo',namespace='tailclient')
        check('overlapping routed source avoids DNS interception','10.66.0.2',53,udp,'echo',source='10.66.0.99',namespace='tailclient')
        for host in ['198.51.100.2','198.51.100.3','28.1.1.1']:
            check('tailnet cannot forward beyond LAN',host,80,udp,namespace='tailclient')
        check('LAN reaches tailnet peer','100.99.0.2',80,udp,'echo')
        check('router management remains reachable','10.66.0.1',18082,udp,'echo',namespace='tailclient')
    for port in [7890,19090,1053]:
        assert ns('client','python3',__file__,'connect','10.66.0.1',str(port)).strip()=='connected'
        assert ns('tailclient','python3',__file__,'connect','10.66.0.1',str(port)).strip()=='blocked'
    for transport in ['tcp','udp']:
        assert ns('client','python3',__file__,'dns','10.66.0.1',transport,'1053').strip()=='dns ok'
        denied=sp.run(['ip','netns','exec','tailclient','python3',__file__,'dns','10.66.0.1',transport,'1053'],stdout=sp.DEVNULL,stderr=sp.DEVNULL)
        assert denied.returncode!=0,'tailnet can use Mihomo DNS directly'
        result=sp.run(['ip','netns','exec','tailclient','python3',__file__,'dns','fd77::2',transport],stdout=sp.DEVNULL,stderr=sp.DEVNULL)
        assert result.returncode!=0,'tailnet IPv6 DNS was intercepted'
    print('PASS tailnet cannot access Mihomo proxy/controller/DNS listeners or hijack IPv6 DNS',flush=True)

def start():
    p=sp.Popen(['/test/mihomo','-service','-d',str(home),'-f',str(home/'config.json')],stdout=log,stderr=log)
    for _ in range(100):
        time.sleep(.1)
        if p.poll() is not None:raise AssertionError('core exited')
        if 'capture_select' in run('nft','list','ruleset') and json.loads(run('curl','-fsS','http://127.0.0.1:19090/configs'))['tun']['enable']:return p
    raise AssertionError('capture not ready')
try:
    firewall=sp.Popen(['/test/native.test','-test.run','^TestLANOnlyFirewallFixture$','-test.timeout=180s'],env=dict(os.environ,MIHOMO_FIREWALL_FIXTURE=str(home)),stdout=log,stderr=log)
    for _ in range(100):
        if firewall.poll() is not None:raise AssertionError('listener firewall fixture failed')
        if (home/'firewall-ready').exists():break
        time.sleep(.1)
    assert (home/'firewall-ready').exists()
    core=start()
    assert config['tun']['device'] in ip('-br','link')
    assert not list(Path('/etc/nftables.d').glob('*auto-redirect*'))
    check_tailnet()
    cleanup=['/test/mihomo','-cleanup','-d',str(home),'-f',str(home/'config.json')]
    assert sp.run(cleanup,stdout=sp.DEVNULL,stderr=sp.DEVNULL).returncode!=0
    check_foreign_rules()
    check('empty provider does not bypass','198.51.100.3',80)
    flow=sp.Popen(['ip','netns','exec','client','python3',__file__,'flow','198.51.100.3','80','1','-'],stdin=sp.PIPE,stdout=sp.PIPE,text=True)
    flow.stdin.write('probe\n');flow.stdin.flush();assert flow.stdout.readline().strip()=='blocked'
    update_bypass(['198.51.100.3/32','8.8.8.8/32','28.1.1.1/32'])
    flow.stdin.write('probe\n');flow.stdin.flush();assert flow.stdout.readline().strip()=='echo'
    flow.terminate();flow.wait();flow=None
    print('PASS provider update bypasses an already captured UDP flow',flush=True)
    check_cn()
    update_bypass(['198.51.100.4/32'])
    check('removed CN address recaptured','198.51.100.3',80)
    check('new CN address bypasses','198.51.100.4',80,expected='echo')
    update_bypass([])
    check('empty update clears bypass','198.51.100.4',80)
    update_bypass(['198.51.100.3/32','8.8.8.8/32','28.1.1.1/32'])
    for port in [22,80,443,8080,8443]:
        check('common port captured','198.51.100.2',port)
        check('udp policy','198.51.100.2',port,True,'echo' if port in [443,8443] else 'blocked')
    check('other port bypass','198.51.100.2',18081,expected='echo')
    check('other UDP bypass','198.51.100.2',18081,True,'echo')
    check('fake overrides ports','28.1.1.1',18081)
    check('fake UDP captured','28.1.1.1',18081,True)
    for port in [443,8443]:check('fake QUIC bypass','28.1.1.1',port,True,'echo')
    for udp in [False,True]:check('private bypass','192.168.70.2',80,udp,'echo')
    check('out of scope source','198.51.100.2',80,expected='echo',source='10.67.0.2')
    check('router output bypass','198.51.100.2',80,expected='echo',namespace=None)
    check('IPv6 bypass','fd77::2',80,expected='echo')
    for dest in ['8.8.8.8','192.168.70.2','fd77::2']:
        for transport in ['tcp','udp']:assert ns('client','python3',__file__,'dns',dest,transport).strip()=='dns ok'
    print('PASS scoped DNS before private/port exclusions, IPv4 and IPv6',flush=True)
    run('fw4','reload')
    check_tailnet()
    check_cn()
    check('capture after firewall reload','198.51.100.2',80)
    check('exception after firewall reload','28.1.1.1',443,True,'echo')
    # Proxy reload must keep TUN, rules and existing exception behavior.
    run('curl','-fsS','-X','PUT','http://127.0.0.1:19090/configs','-H','Content-Type: application/json','-d',json.dumps({'path':str(home/'config.json')}))
    check('capture after config reload','198.51.100.2',80)
    check_cn()
    config['rules']=['MATCH,DIRECT']
    (home/'config.json').write_text(json.dumps(config))
    run('curl','-fsS','-X','PUT','http://127.0.0.1:19090/configs','-H','Content-Type: application/json','-d',json.dumps({'path':str(home/'config.json')}))
    check('captured TCP forwards through Mihomo','198.51.100.2',80,expected='echo')
    check('captured UDP forwards through Mihomo','198.51.100.2',80,True,'echo')
    config['tun']['mtu']=1400
    (home/'config.json').write_text(json.dumps(config))
    run('curl','-fsS','-X','PUT','http://127.0.0.1:19090/configs','-H','Content-Type: application/json','-d',json.dumps({'path':str(home/'config.json')}))
    check_foreign_rules()
    check('forwarding after TUN recreation','198.51.100.2',80,expected='echo')
    config['rules']=['MATCH,REJECT']
    (home/'config.json').write_text(json.dumps(config))
    # Restart after abrupt death must replace stale state, not duplicate it.
    core.kill();core.wait();run(*cleanup);run(*cleanup)
    assert 'table inet mihomo {' not in run('nft','list','ruleset')
    check_foreign_rules()
    core=start()
    check_foreign_rules()
    check('capture after crash restart','198.51.100.2',80)
    check_cn()
    check('bypass after crash restart','198.51.100.2',8443,True,'echo')
    core.terminate();assert core.wait(timeout=15)==0;core=None
    assert 'table inet mihomo {' not in run('nft','list','ruleset')
    assert config['tun']['device'] not in ip('-br','link')
    assert 'lookup 100' not in ip('rule')
    assert not list(Path('/etc/nftables.d').glob('*auto-redirect*'))
    check_foreign_rules()
    print('PASS clean shutdown removes TUN, routes, nftables and fw4 include',flush=True)
    missing=json.loads(json.dumps(config))
    missing['tun']['capture-policy']['source-interfaces']=['missing-lan']
    (home/'missing.json').write_text(json.dumps(missing))
    failed=sp.run(['/test/mihomo','-t','-d',str(home),'-f',str(home/'missing.json')],stdout=sp.PIPE,stderr=sp.STDOUT,text=True)
    assert failed.returncode!=0 and 'missing-lan' in failed.stdout,failed.stdout
    assert 'table inet mihomo {' not in run('nft','list','ruleset')
    print('PASS missing LAN fails validation without installing interception',flush=True)
    occupied=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    occupied.bind(('0.0.0.0',1053));occupied.listen()
    failed=sp.Popen(['/test/mihomo','-service','-d',str(home),'-f',str(home/'config.json')],stdout=log,stderr=log)
    assert failed.wait(timeout=10)!=0
    occupied.close()
    assert 'table inet mihomo {' not in run('nft','list','ruleset')
    print('PASS DNS bind failure exits without installing interception',flush=True)
    (home/'firewall-stop').touch();assert firewall.wait(timeout=10)==0;firewall=None
    assert 'table inet mihomo_listeners' not in run('nft','list','ruleset')
    # Stopping/crashing the core does not remove package-owned firewall policy.
    assert 'mh_tailnet' in run('nft','list','table','inet','fw4')
    run(*helper,'remove');run(*helper,'remove')
    state=run('uci','export','firewall')
    assert 'mihomo_' not in state and 'lan_wan' in state
    check('removed package leaves no tailnet forwarding allow','10.66.0.2',7890,namespace='tailclient')
    print('PASS package removal deletes only owned UCI permissions',flush=True)
finally:
    if firewall and firewall.poll() is None:
        (home/'firewall-stop').touch();firewall.wait(timeout=10)
    for process in [lan_echo,tail_echo,router_echo]:process.terminate();process.wait()
    if flow and flow.poll() is None:flow.terminate();flow.wait()
    if core and core.poll() is None:core.terminate();core.wait(timeout=15)
    echo.terminate();echo.wait()
    if sys.exc_info()[0]:log.flush();print((home/'core.log').read_text(),file=sys.stderr)
