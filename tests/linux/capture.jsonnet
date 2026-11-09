local capture = import 'capture.libsonnet';
capture() + {
  'external-controller': '0.0.0.0:19090',
  'mixed-port': 7890,
  'allow-lan': true,
  'log-level': 'debug',
  hosts: { 'probe.test': '192.0.2.42' },
  'rule-providers': {
    'cn-ip': { type: 'file', behavior: 'ipcidr', format: 'yaml', path: './cn-ip.yaml' },
  },
  dns+: {
    'enhanced-mode': 'redir-host',
    'use-hosts': true,
    nameserver: ['127.0.0.1:15353'],
    'default-nameserver': ['127.0.0.1:15353'],
  },
  rules: ['MATCH,REJECT'],
}
