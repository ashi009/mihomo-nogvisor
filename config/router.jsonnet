local capture = import 'capture.libsonnet';
local tailnet = import 'tailnet.libsonnet';
// Supply provider/rule policy as base. This file contains no subscriptions or keys.
function(base, hostname='cito-102', lan='192.168.20.0/24', stateDir='tailnet', authKeyFile='')
  local cp = capture(lan);
  local tn = tailnet(hostname, [lan], stateDir, authKeyFile=authKeyFile);
  local dns = std.get(base, 'dns', {});
  base + cp + tn + {
    dns: dns + cp.dns + tn.dns + {
      'fake-ip-filter': std.set(std.get(dns, 'fake-ip-filter', []) + tn.dns['fake-ip-filter']),
      'nameserver-policy': std.get(dns, 'nameserver-policy', {}) + tn.dns['nameserver-policy'],
    },
  }
