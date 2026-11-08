import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('upstream', Path(__file__).resolve().parents[2] / 'scripts/update-upstream.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


def commit(i, message):
    return {'sha': f'{i:040x}', 'commit': {'message': message}}


class UpstreamTests(unittest.TestCase):
    def test_pagination_keeps_all_288_commits(self):
        calls = []
        def fetch(url):
            calls.append(url)
            page = int(url.rsplit('=', 1)[1])
            return {'status': 'ahead', 'total_commits': 288,
                    'commits': [commit(i, 'fix') for i in range((page-1)*100, min(page*100, 288))]}
        _, commits = u.comparison('owner/repo', 'old', 'new', fetch)
        self.assertEqual(len(commits), 288)
        self.assertEqual(len(calls), 3)

    def test_branch_rewrite_needs_manual_review(self):
        with self.assertRaisesRegex(ValueError, 'branch rewrite'):
            u.comparison('o/r', 'old', 'new', lambda _: {'status': 'diverged'})

    def test_truncated_history_is_rejected(self):
        def fetch(url):
            return {'status': 'ahead', 'total_commits': 2, 'commits': [commit(1, 'fix')] if url.endswith('&page=1') else []}
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            u.comparison('o/r', 'old', 'new', fetch)

    def test_dependency_and_patch_impact_with_linked_highlights(self):
        old, new = 'a'*40, 'b'*40
        pin = {'repository': 'vernesong/mihomo', 'branch': 'Alpha', 'revision': old,
               'dependencies': {'github.com/metacubex/sing-tun': 'v0.4.21'},
               'native_dependencies': {'tailscale.com': 'v1.102.3'}}
        commits = [commit(1, 'fix: Smart deadlock'), commit(2, 'fix: DNS routing'), commit(3, 'Merge upstream')]
        updated, path, report, body, branch = u.render(pin, {'sha': new},
            {'files': [{'filename': 'main.go'}]}, commits,
            'require (\n github.com/metacubex/sing-tun v0.4.29\n)', {'main.go'}, 'ashi009/mihomo-nogvisor')
        self.assertEqual(updated['revision'], new)
        self.assertEqual(updated['dependencies']['github.com/metacubex/sing-tun'], 'v0.4.29')
        self.assertEqual(pin['revision'], old)
        self.assertEqual(updated['native_dependencies'], {'tailscale.com': 'v1.102.3'})
        self.assertIn('Smart policy: fix: Smart deadlock', body)
        self.assertIn('DNS and routing: fix: DNS routing', body)
        self.assertIn('`main.go`', body)
        self.assertIn('Merge upstream', report)
        self.assertNotIn('Merge upstream', body)
        self.assertIn(f'/blob/{branch}/{path}', body)

    def test_missing_dependency_cannot_be_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, 'removed'):
            u.dependencies('module x', {'github.com/metacubex/tailscale': 'v1'})

    def test_upstream_text_is_literal_markdown(self):
        line = u.commit_line('o/r', commit(1, '<script>@everyone [click](evil) `cmd`\nbody'))
        self.assertNotIn('<script>', line)
        self.assertNotIn('@everyone', line)
        self.assertIn('\\[click\\]', line)
        self.assertNotIn('body', line)


if __name__ == '__main__':
    unittest.main()
