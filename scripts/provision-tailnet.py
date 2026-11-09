#!/usr/bin/env python3
"""Mint a router auth key locally using the pinned upstream OAuth helper."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]


def provision(config_path, output):
    config = json.loads(config_path.read_text())
    client_id = config['client-id']
    tags = config['tags']
    preauthorized = config['preauthorized']
    if not isinstance(client_id, str) or not client_id:
        raise ValueError('client-id must be a nonempty string')
    if not isinstance(tags, list) or not tags or not all(
        isinstance(tag, str) and re.fullmatch(r'tag:[a-zA-Z0-9-]+', tag)
        for tag in tags
    ):
        raise ValueError('tags must contain at least one tag:name')
    if not isinstance(preauthorized, bool):
        raise ValueError('preauthorized must be a boolean')
    secret_path = config_path.parent / config['client-secret-file']
    secret = secret_path.read_text().strip()
    if not secret:
        raise ValueError('client-secret-file is empty')
    version = json.loads((REPO / 'upstream.json').read_text())['native_dependencies']['tailscale.com']
    env = dict(os.environ, TS_API_CLIENT_ID=client_id, TS_API_CLIENT_SECRET=secret,
               GOWORK='off', GOFLAGS='')
    for name in ('GOOS', 'GOARCH', 'GOARM', 'GOARM64', 'TS_BASE_URL'):
        env.pop(name, None)
    # Credentials stay in the local child environment, never in argv or output.
    command = ['go', 'run', f'tailscale.com/cmd/get-authkey@{version}',
               '-reusable=false', '-ephemeral=false',
               f'-preauth={str(preauthorized).lower()}', '-tags=' + ','.join(tags)]
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as file, tempfile.TemporaryDirectory() as work:
            result = subprocess.run(command, cwd=work, env=env, capture_output=True,
                                    text=True, timeout=300)
            if result.returncode:
                # Upstream errors can include HTTP responses; do not echo secrets.
                raise RuntimeError('OAuth provisioning failed; check connectivity, '
                                   'Go toolchain, auth_keys scope and allowed tags')
            key = result.stdout.strip()
            if not re.fullmatch(r'tskey-auth-[A-Za-z0-9_-]+', key):
                raise RuntimeError('upstream helper did not return an auth key')
            file.write(key + '\n')
    except BaseException:
        output.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path, help='JSON rendered from config/provision.jsonnet')
    parser.add_argument('output', type=Path, help='new private auth-key file; never overwritten')
    args = parser.parse_args()
    try:
        provision(args.config, args.output)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'{error}\n')
    print(f'Wrote auth key to {args.output}')


if __name__ == '__main__':
    main()
