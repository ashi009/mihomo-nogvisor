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
                data,peer=s.recvfrom(2048);s.sendto(data,peer)
        else:
            s.listen()
            while True:
                c,_=s.accept()
                try:c.settimeout(1);c.sendall(c.recv(2048))
                except OSError:pass
                c.close()
    for addr in ['198.51.100.2','192.168.70.2','28.1.1.1','fd77::2']:
        for port in [22,80,443,8080,8443,18081]:
            for udp in [False,True]:threading.Thread(target=serve,args=(addr,port,udp),daemon=True).start()
    time.sleep(300)
    sys.exit()

if len(sys.argv)>1 and sys.argv[1]=='probe':
    _,_,host,port,udp,source=sys.argv
    s=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_DGRAM if udp=='1' else socket.SOCK_STREAM)
    s.settimeout(.6)
    if source!='-':s.bind((source,0))
    try:
        s.connect((host,int(port)));s.sendall(b'capture-probe');print('echo' if s.recv(64)==b'capture-probe' else 'blocked')
    except OSError:print('blocked')
    sys.exit()

if len(sys.argv)>1 and sys.argv[1]=='dns':
    host=sys.argv[2];tcp=sys.argv[3]=='tcp'
    q=struct.pack('!6H',1234,0x100,1,0,0,0)+b'\x05probe\x04test\x00'+struct.pack('!2H',1,1)
    s=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)
    s.settimeout(2);s.connect((host,53))
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

for name in ['client','target']:ip('netns','add',name)
for name,dev,local,remote in [('client','br-lan','10.66.0.1/24','10.66.0.2/24'),('target','wan','203.0.113.1/24','203.0.113.2/24')]:
    ip('link','add',dev,'type','veth','peer','name',dev+'peer')
    ip('link','set',dev+'peer','netns',name)
    ip('addr','add',local,'dev',dev);ip('link','set',dev,'up')
    ns(name,'ip','addr','add',remote,'dev',dev+'peer');ns(name,'ip','link','set',dev+'peer','up');ns(name,'ip','link','set','lo','up')
    ns(name,'ip','route','add','default','via',local.split('/')[0])
ns('client','ip','addr','add','10.67.0.2/24','dev','br-lanpeer')
ip('route','add','10.67.0.0/24','dev','br-lan')
for prefix in ['198.51.100.2/32','192.168.70.2/32','28.1.1.1/32']:ns('target','ip','addr','add',prefix,'dev','lo');ip('route','add',prefix,'via','203.0.113.2')
for namespace,device,addr in [(None,'br-lan','fd66::1/64'),('client','br-lanpeer','fd66::2/64'),(None,'wan','fd77::1/64'),('target','wanpeer','fd77::2/64')]:
    args=['ip','-6','addr','add',addr,'dev',device,'nodad'];ns(namespace,*args) if namespace else run(*args)
ns('client','ip','-6','route','add','default','via','fd66::1');ns('target','ip','-6','route','add','default','via','fd77::1')
# Exercise the same generated fw4 include and reload path as OpenWrt.
Path('/etc/nftables.d').mkdir(exist_ok=True)
Path('/usr/sbin/fw4').write_text('#!/bin/sh\nnft delete table inet fw4 2>/dev/null || :\n{ echo "table inet fw4 {"; cat /etc/nftables.d/*.nft 2>/dev/null || :; echo "}"; } | nft -f -\n')
os.chmod('/usr/sbin/fw4',0o755);run('fw4','reload')
echo=sp.Popen(['ip','netns','exec','target','python3',__file__,'echo'])
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
def start():
    p=sp.Popen(['/test/mihomo','-service','-d',str(home),'-f',str(home/'config.json')],stdout=log,stderr=log)
    for _ in range(100):
        time.sleep(.1)
        if p.poll() is not None:raise AssertionError('core exited')
        if 'capture_select' in run('nft','list','ruleset') and json.loads(run('curl','-fsS','http://127.0.0.1:19090/configs'))['tun']['enable']:return p
    raise AssertionError('capture not ready')
try:
    core=start()
    cleanup=['/test/mihomo','-cleanup','-d',str(home),'-f',str(home/'config.json')]
    assert sp.run(cleanup,stdout=sp.DEVNULL,stderr=sp.DEVNULL).returncode!=0
    check_foreign_rules()
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
    check('capture after firewall reload','198.51.100.2',80)
    check('exception after firewall reload','28.1.1.1',443,True,'echo')
    # Proxy reload must keep TUN, rules and existing exception behavior.
    run('curl','-fsS','-X','PUT','http://127.0.0.1:19090/configs','-H','Content-Type: application/json','-d',json.dumps({'path':str(home/'config.json')}))
    check('capture after config reload','198.51.100.2',80)
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
    assert 'table inet mihomo' not in run('nft','list','ruleset')
    check_foreign_rules()
    core=start()
    check_foreign_rules()
    check('capture after crash restart','198.51.100.2',80)
    check('bypass after crash restart','198.51.100.2',8443,True,'echo')
    core.terminate();assert core.wait(timeout=15)==0;core=None
    assert 'table inet mihomo' not in run('nft','list','ruleset')
    assert 'utun' not in ip('-br','link')
    assert 'lookup 100' not in ip('rule')
    assert not list(Path('/etc/nftables.d').glob('*mihomo*'))
    check_foreign_rules()
    print('PASS clean shutdown removes TUN, routes, nftables and fw4 include',flush=True)
    occupied=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    occupied.bind(('0.0.0.0',1053));occupied.listen()
    failed=sp.Popen(['/test/mihomo','-service','-d',str(home),'-f',str(home/'config.json')],stdout=log,stderr=log)
    assert failed.wait(timeout=10)!=0
    occupied.close()
    assert 'table inet mihomo' not in run('nft','list','ruleset')
    print('PASS DNS bind failure exits without installing interception',flush=True)
finally:
    if core and core.poll() is None:core.terminate();core.wait(timeout=15)
    echo.terminate();echo.wait()
    if sys.exc_info()[0]:log.flush();print((home/'core.log').read_text(),file=sys.stderr)
