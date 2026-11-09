import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'provision', Path(__file__).resolve().parents[2] / 'scripts/provision-tailnet.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.config = self.root / 'provision.json'
        self.output = self.root / 'tailnet.key'
        (self.root / 'oauth.secret').write_text('local-oauth-secret\n')
        self.config.write_text(json.dumps({
            'client-id': 'client', 'client-secret-file': 'oauth.secret',
            'tags': ['tag:router'], 'preauthorized': True,
        }))

    def test_only_node_key_is_written_and_existing_key_is_never_replaced(self):
        def upstream(command, **kwargs):
            self.assertNotIn('local-oauth-secret', ' '.join(command))
            self.assertEqual(kwargs['env']['TS_API_CLIENT_SECRET'], 'local-oauth-secret')
            self.assertNotIn('TS_BASE_URL', kwargs['env'])
            self.assertIn('-reusable=false', command)
            self.assertIn('-ephemeral=false', command)
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
            return subprocess.CompletedProcess(command, 0, 'tskey-auth-node-key\n', '')

        with patch.dict(os.environ, {'TS_BASE_URL': 'https://untrusted.invalid'}):
            with patch.object(p.subprocess, 'run', side_effect=upstream) as run:
                p.provision(self.config, self.output)
                with self.assertRaises(FileExistsError):
                    p.provision(self.config, self.output)
                self.assertEqual(run.call_count, 1)
        self.assertEqual(self.output.read_text(), 'tskey-auth-node-key\n')

    def test_failure_does_not_leave_a_key_or_expose_http_response(self):
        result = subprocess.CompletedProcess([], 1, '', 'secret echoed by remote server')
        with patch.object(p.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as caught:
                p.provision(self.config, self.output)
        self.assertNotIn('secret', str(caught.exception))
        self.assertFalse(self.output.exists())

    def test_invalid_tags_do_not_mint_a_key(self):
        config = json.loads(self.config.read_text())
        config['tags'] = []
        self.config.write_text(json.dumps(config))
        with patch.object(p.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                p.provision(self.config, self.output)
            run.assert_not_called()
        self.assertFalse(self.output.exists())
