"""Root-private forward identity receipt and refusal checks."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, skipUnless, main
from unittest.mock import patch


DEPLOY = Path(__file__).resolve().parents[2] / 'deploy'
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location('ip_forward_identity',
                                             DEPLOY / 'ip_forward_identity.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


@skipUnless(os.name == 'posix' and getattr(os, 'geteuid', lambda: -1)() == 0,
            'root POSIX private-file semantics')
class ForwardIdentityTest(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='atom-forward-identity-')
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.old_revision, self.next_revision = 'a' * 40, 'b' * 40
        self.old_image, self.next_image = 'sha256:' + 'c' * 64, 'sha256:' + 'd' * 64
        backup, state = root / 'backups', root / 'state'
        backup.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        source = backup / ('candidate-' + self.old_revision[:12])
        caddy = source / 'caddy'
        source.mkdir(mode=0o700)
        caddy.mkdir(mode=0o700)
        self.base = b'{\n  default_sni 192.0.2.10\n}\n\n192.0.2.10 { respond "console" 200 }\n'
        self.active_bytes = self.base + b'\nhttps://192.0.2.10:20000 { respond ok 200 }\n'
        for name, payload in (('Caddyfile.base', self.base),
                              ('Caddyfile', self.active_bytes)):
            path = caddy / name
            path.write_bytes(payload)
            path.chmod(0o600)
        self.config = module.protected_cutover.CutoverConfig(
            'atom-candidate', 'atom-candidate-broker', root / 'unused-data',
            root / 'unused-broker', backup, state, 'test-network', 18080,
            18, 3, Path('/usr/bin/docker'), Path('/var/run/docker.sock'))
        self.ids = {role: f'{index:064x}' for index, role in
                    enumerate(module.ROLES, start=1)}
        self.service_ips = {role: f'172.30.0.{index + 2}'
                            for index, role in enumerate(module.PINNED_ROLES)}
        self.active = {'revision': self.old_revision, 'imageId': self.old_image,
                       'candidateDirectory': str(source), 'containerIds': self.ids,
                       'caddySha256': hashlib.sha256(self.active_bytes).hexdigest(),
                       'successor': {'revision': self.next_revision,
                                     'imageId': self.next_image}}

    def _inspect(self, _docker, _kind, name):
        role = next(role for role in module.ROLES
                    if module._name(self.config, role) == name)
        item = {'Name': '/' + name, 'Id': self.ids[role],
                'State': {'Running': True}}
        if role in self.service_ips:
            address = self.service_ips[role]
            item['NetworkSettings'] = {'Networks': {self.config.network: {
                'IPAddress': address,
                'IPAMConfig': {'IPv4Address': address}}}}
        return item

    def test_receipt_preserves_exact_bytes_and_rejects_tampering(self):
        with patch.object(module.protected_cutover, '_inspect', side_effect=self._inspect), \
                patch.object(module.ip_cutover_rollback, '_inspect', return_value=None):
            path = module.capture(self.config, self.active, self.next_revision,
                                  self.next_image)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        record = module.read(path, config=self.config,
                             successor_revision=self.next_revision)
        self.assertEqual(record['containerIds'], self.ids)
        self.assertEqual(record['serviceIps'], self.service_ips)
        self.assertEqual(module.caddy_bytes(record, 'base'), self.base)
        self.assertEqual(module.caddy_bytes(record, 'active'), self.active_bytes)
        record['caddy']['active']['base64'] = 'AAAA'
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaisesRegex(module.IdentityError,
                                    'invalid_forward_caddy_receipt'):
            module.read(path, config=self.config,
                        successor_revision=self.next_revision)

    def test_held_name_conflict_refuses_before_writing_receipt(self):
        with patch.object(module.protected_cutover, '_inspect', side_effect=self._inspect), \
                patch.object(module.ip_cutover_rollback, '_inspect',
                             return_value={'Id': 'f' * 64}):
            with self.assertRaisesRegex(module.IdentityError,
                                        'forward_held_name_occupied'):
                module.capture(self.config, self.active, self.next_revision,
                               self.next_image)
        self.assertFalse((self.config.state_dir /
                          (self.next_revision + '.forward.json')).exists())


if __name__ == '__main__':
    main()
