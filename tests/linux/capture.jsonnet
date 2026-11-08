local capture = import 'capture.libsonnet';
capture('10.66.0.0/24') + {
  'external-controller': '127.0.0.1:19090',
  'log-level': 'debug',
  hosts: { 'probe.test': '192.0.2.42' },
  dns+: {
    'enhanced-mode': 'redir-host',
    'use-hosts': true,
    nameserver: ['127.0.0.1:15353'],
    'default-nameserver': ['127.0.0.1:15353'],
  },
  rules: ['MATCH,REJECT'],
}
