// Pure configuration fragment. Enrollment keys are provisioned as a private file.
function(hostname='', prefixes=[], stateDir='tailnet', interface='tailscale0', authKeyFile='', advertiseInterfaces=[]) {
  tailnet: {
    enable: true,
    'firewall-mode': 'nftables',
    name: 'tailnet',
    hostname: hostname,
    interface: interface,
    'state-dir': stateDir,
    'control-url': 'https://controlplane.tailscale.com',
    'auth-key-file': authKeyFile,
    'accept-routes': true,
    'advertise-routes': prefixes,
    'advertise-interfaces': advertiseInterfaces,
    port: 41641,
  },
  dns: {
    'fake-ip-filter': ['+.ts.net'],
    'nameserver-policy': { '+.ts.net': ['tailscale://tailnet'] },
  },
}
