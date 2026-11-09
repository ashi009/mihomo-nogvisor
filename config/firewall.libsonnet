// Emit /etc/mihomo/firewall.uci alongside YAML from the same rendered config.
function(config, lanZone='lan')
  local tn = std.get(config, 'tailnet', {});
  local quote(s) =
    assert std.length(s) > 0 && std.length(std.findSubstr("'", s)) == 0 && std.length(std.findSubstr('\n', s)) == 0 : 'invalid UCI value';
    "'" + s + "'";
  local endpointPort(address) =
    if address == '' then 0 else std.parseInt(std.split(address, ':')[std.length(std.split(address, ':')) - 1]);
  local dns = std.get(config, 'dns', {});
  local ports = std.set(
    [std.get(config, key, 0) for key in ['port', 'socks-port', 'mixed-port', 'redir-port', 'tproxy-port']] +
    [endpointPort(std.get(config, key, '')) for key in ['external-controller', 'external-controller-tls']] +
    (if std.get(dns, 'enable', false) then [endpointPort(std.get(dns, 'listen', ''))] else []) +
    [std.get(listener, 'port', 0) for listener in std.get(config, 'listeners', [])]
  );
  local activePorts = [p for p in ports if p != 0];
  local section(kind, name, options) =
    'config ' + kind + ' ' + quote(name) + '\n' +
    std.join('', ['\toption ' + key + ' ' + quote(std.toString(options[key])) + '\n' for key in std.objectFields(options)]) + '\n';
  assert std.all([std.isNumber(p) && p >= 1 && p <= 65535 && p == std.floor(p) for p in activePorts]) : 'listeners require fixed numeric ports';
  if !std.get(tn, 'enable', false) then 'package firewall\n' else
  'package firewall\n\n' +
  section('zone', 'mihomo_tailnet', {
    name: 'mh_tailnet', device: std.get(tn, 'interface', 'tailscale0'),
    input: 'ACCEPT', output: 'ACCEPT', forward: 'REJECT', masq: 1, mtu_fix: 1,
  }) +
  (if std.length(activePorts) == 0 then '' else section('rule', 'mihomo_listeners', {
    name: 'Mihomo: protect router listeners', src: 'mh_tailnet', proto: 'tcp udp',
    dest_port: std.join(' ', [std.toString(p) for p in activePorts]), target: 'REJECT',
  })) +
  section('forwarding', 'mihomo_tailnet_lan', { src: 'mh_tailnet', dest: lanZone }) +
  section('forwarding', 'mihomo_lan_tailnet', { src: lanZone, dest: 'mh_tailnet' })
