local tailnet = import 'tailnet.libsonnet';
tailnet('probe-gateway', ['192.0.2.0/24'], 'tailnet', 'tailtest0')
