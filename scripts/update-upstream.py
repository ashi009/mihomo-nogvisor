#!/usr/bin/env python3
"""Resolve Alpha, update pins, and write a linked changelog; never execute upstream text."""
import argparse
import base64
import html
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote


def api(endpoint):
    return json.loads(subprocess.check_output(['gh', 'api', endpoint], text=True))


def comparison(repo, old, new, fetch=api):
    endpoint = f'repos/{repo}/compare/{old}...{new}'
    first = fetch(endpoint + '?per_page=100&page=1')
    if first['status'] != 'ahead':
        raise ValueError('upstream is not a descendant of our pin; review the branch rewrite manually')
    commits = list(first['commits'])
    page = 2
    while len(commits) < first['total_commits']:
        more = fetch(endpoint + f'?per_page=100&page={page}')['commits']
        if not more:
            raise ValueError('incomplete upstream commit history')
        commits.extend(more)
        page += 1
    if len({c['sha'] for c in commits}) != first['total_commits']:
        raise ValueError('duplicate or inconsistent upstream history')
    return first, commits


def text(value):
    value = html.escape(' '.join(value.split()), quote=False).replace('@', '&#64;')
    return re.sub(r'([\\`*\[\]_])', r'\\\1', value)


def commit_line(repo, commit):
    title = text(commit['commit']['message'].splitlines()[0])
    sha = commit['sha']
    return f'{title} ([{sha[:8]}](https://github.com/{repo}/commit/{sha}))'


def highlights(repo, commits):
    categories = [
        ('Smart policy', r'smart|lightgbm|policy.priority'),
        ('Security and reliability', r'cve[- ]|secur|vulnerab|panic|crash|deadlock|race|leak'),
        ('DNS and routing', r'\bdns\b|\btun\b|route|routing|nft|netlink|redirect'),
        ('Protocols', r'wireguard|tailscale|quic|snell|vless|vmess|trojan|shadowsocks|sudoku|easytier|zerotier'),
    ]
    selected = set()
    lines = []
    candidates = [c for c in reversed(commits) if not c['commit']['message'].lower().startswith('merge ')]
    for label, pattern in categories:
        matches = [c for c in candidates if c['sha'] not in selected and re.search(pattern, c['commit']['message'].splitlines()[0], re.I)][:3]
        for c in matches:
            selected.add(c['sha'])
            lines.append(f'- {label}: {commit_line(repo, c)}')
    if not lines:
        lines = ['- ' + commit_line(repo, c) for c in candidates[:5]]
    return '\n'.join(lines)


def dependencies(go_mod, previous):
    result = {}
    for module in previous:
        match = re.search(r'^\s*' + re.escape(module) + r'\s+(v[0-9A-Za-z.+-]+)(?:\s|$)', go_mod, re.M)
        if not match:
            raise ValueError(f'upstream removed {module}; its patch queue needs manual review')
        result[module] = match[1]
    return result


def render(pin, head, summary, commits, go_mod, patch_paths, destination):
    repo, old, new = pin['repository'], pin['revision'], head['sha']
    updated = dict(pin, revision=new, dependencies=dependencies(go_mod, pin['dependencies']))
    branch = 'upstream/mihomo-' + new[:12]
    report_path = f'updates/{new[:12]}.md'
    compare_url = f'https://github.com/{repo}/compare/{old}...{new}'
    intro = f'Update {repo} {pin["branch"]} from `{old[:12]}` to `{new[:12]}` ({len(commits)} commits).'
    selected = highlights(repo, commits)
    files = {f['filename'] for f in summary.get('files', [])}
    touched = sorted(files & patch_paths)
    impact = []
    for module, version in updated['dependencies'].items():
        previous = pin['dependencies'][module]
        if previous != version:
            impact.append(f'- Dependency: `{module}` changes from `{previous}` to `{version}`; recheck its independent patch queue.')
    if touched:
        impact.append('- Upstream changed our Mihomo hook files: ' + ', '.join(f'`{p}`' for p in touched) + '.')
    if len(summary.get('files', [])) >= 300:
        impact.append('- GitHub capped the changed-file list at 300; the comparison may contain additional patch overlaps.')
    impact_text = '\n'.join(impact)
    report = (f'# Upstream {new[:12]}\n\n{intro}\n\n[Full comparison]({compare_url})\n\n'
              f'## Highlights\n\nSelected upstream commit subjects; these are changes to review, not verified behavior.\n\n{selected}\n\n'
              f'## Integration impact\n\n{impact_text or "No pinned dependency or listed hook-file changes."}\n\n'
              '## All commits\n\n' + '\n'.join('- ' + commit_line(repo, c) for c in reversed(commits)) + '\n')
    body = (intro + '\n\n' + selected + '\n\n' + impact_text + '\n\n'
            f'[Complete changelog](https://github.com/{destination}/blob/{branch}/{report_path}) · '
            f'[Upstream comparison]({compare_url})\n\n'
            'The updater keeps this PR draft until native Linux checks pass. Conflicting patches remain for review; '
            'the updater does not rewrite them. Merging does not deploy to routers.\n')
    return updated, report_path, report, body, branch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pin_path = args.root / 'upstream.json'
    pin = json.loads(pin_path.read_text())
    repo = pin['repository']
    if repo != 'vernesong/mihomo' or pin['branch'] != 'Alpha' or not re.fullmatch('[0-9a-f]{40}', pin['revision']):
        raise ValueError('invalid upstream pin')
    head = api(f'repos/{repo}/commits/' + quote(pin['branch'], safe=''))
    if not re.fullmatch('[0-9a-f]{40}', head['sha']):
        raise ValueError('invalid upstream SHA')
    args.output.mkdir(parents=True, exist_ok=True)
    result = {'changed': False}
    if head['sha'] != pin['revision']:
        summary, commits = comparison(repo, pin['revision'], head['sha'])
        module = api(f'repos/{repo}/contents/go.mod?ref={head["sha"]}')
        go_mod = base64.b64decode(module['content']).decode()
        patch_paths = set()
        for patch in (args.root / 'patches').glob('*.patch'):
            patch_paths.update(re.findall(r'^\+\+\+ b/(.+)$', patch.read_text(), re.M))
        updated, report_path, report, body, branch = render(pin, head, summary, commits, go_mod, patch_paths, os.environ.get('GITHUB_REPOSITORY', 'ashi009/mihomo-nogvisor'))
        pin_path.write_text(json.dumps(updated, indent=2) + '\n')
        target = args.root / report_path
        target.parent.mkdir(exist_ok=True)
        target.write_text(report)
        (args.output / 'body.md').write_text(body)
        result = {'changed': True, 'branch': branch, 'revision': head['sha'], 'report': report_path,
                  'title': 'build: update mihomo to ' + head['sha'][:12]}
    (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in result.items():
                output.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
