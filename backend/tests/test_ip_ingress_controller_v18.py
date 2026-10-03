"""Atomic ingress file application and failure recovery against a real ledger."""
import hashlib
from email.message import Message
from urllib.error import HTTPError

import pytest

from app import ip_ingress_controller as controller_module
from app import ip_ingress as ingress_module
from app.ip_ingress import (IngressError, IpIngressConfig, probe_ip_maintenance_routes,
                            render_ip_caddyfile, render_ip_maintenance_routes)
from app.ip_ingress_controller import DockerCaddy, IpIngressController
from app.migrations import migrate
from app.project_origins import ProjectOriginRepository
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_rollback_v14_repository import historical
from test_v13_content_consumers import published
from test_verifier_authority import authorized


class ObservedCaddy(DockerCaddy):
    def __init__(self):
        super().__init__('caddy-test', '/etc/caddy/Caddyfile')
        self.validated = []
        self.reloads = 0
        self.fail_validation = False
        self.fail_reload_at = set()
        self.mount_checked = False

    def ensure_directory_bind(self, directory):
        assert directory.is_dir()
        self.mount_checked = True

    def validate(self, candidate):
        self.validated.append(candidate)
        if self.fail_validation:
            raise IngressError('caddy_validation_failed')

    def reload(self):
        self.reloads += 1
        if self.reloads in self.fail_reload_at:
            raise IngressError('caddy_reload_failed')


@pytest.fixture
def ingress(historical, tmp_path):
    path, _store, _intent, _source, _displaced = historical
    for version in range(15, 19):
        migrate(path, tmp_path / f'before-ingress-v{version}.db', target_version=version)
    origins = ProjectOriginRepository(path, first_port=20000, last_port=20003)
    origins.reserve('project')
    base = tmp_path / 'Caddyfile.base'
    active = tmp_path / 'Caddyfile'
    base.write_text('https://192.0.2.10 { respond "console" 200 }\n', encoding='utf-8')
    active.write_bytes(b'previous known-good config\n')
    config = IpIngressConfig('192.0.2.10', 'preview:8000', 'public:8000',
                             'https://acme.example.test/directory')
    return origins, config, base, active


def test_reconcile_uses_ledger_and_reloads_again_after_restart(ingress):
    origins, config, base, active = ingress
    caddy = ObservedCaddy()
    observed = []
    def probe(routes, selected):
        observed.append((routes, selected))
    controller = IpIngressController(origins, config, base, active, caddy,
                                      probe=probe, probe_budget_seconds=0)
    digest = controller.reconcile()
    expected = render_ip_caddyfile(base.read_text('utf-8'), origins, config).encode()
    assert active.read_bytes() == expected
    assert digest == hashlib.sha256(expected).hexdigest()
    assert caddy.mount_checked and caddy.validated == [expected]
    assert caddy.reloads == 1 and observed == [(origins.active_routes(), config.address)]
    # A restart must reapply even if the config bytes have not changed.
    assert controller.reconcile() == digest
    assert caddy.reloads == 2 and len(observed) == 2


def test_forward_maintenance_retains_exact_tls_origins_but_denies_content(ingress):
    origins, config, _base, _active = ingress
    maintenance_base = 'https://192.0.2.10 {\n  header Cache-Control "no-store"\n  respond "maintenance" 503\n}\n'
    routes = origins.active_routes()
    rendered = render_ip_maintenance_routes(maintenance_base, routes, config)
    assert rendered.count('respond "正在更新，请稍后刷新" 503') == len(routes)
    assert rendered.count('profile shortlived') == len(routes)
    assert 'https://192.0.2.10:20000 {' in rendered
    assert 'https://192.0.2.10:20001 {' in rendered
    assert 'reverse_proxy' not in rendered
    assert rendered.startswith(maintenance_base.strip())
    with pytest.raises(IngressError, match='invalid_origin_route'):
        render_ip_maintenance_routes(maintenance_base, routes + routes[:1], config)
    with pytest.raises(IngressError, match='ingress_port_already_configured'):
        render_ip_maintenance_routes(maintenance_base + '\nhttps://192.0.2.10:20000 { }\n',
                                     routes, config)


def test_forward_maintenance_probe_requires_tls_503_no_store_without_cookies(ingress,
                                                                              monkeypatch):
    origins, config, _base, _active = ingress
    observed = []
    headers = Message()
    headers['Cache-Control'] = 'no-store'

    class Opener:
        def open(self, request, timeout):
            observed.append((request.full_url, request.get_method(), timeout))
            raise HTTPError(request.full_url, 503, 'maintenance', headers, None)

    monkeypatch.setattr(ingress_module, 'build_opener', lambda *_args: Opener())
    probe_ip_maintenance_routes(origins.active_routes(), config.address)
    assert len(observed) == 2
    assert all(method == 'POST' and url.endswith('/_atom/health')
               for url, method, _timeout in observed)
    headers['Set-Cookie'] = 'bad=1'
    with pytest.raises(IngressError, match='maintenance_probe_mismatch'):
        probe_ip_maintenance_routes(origins.active_routes(), config.address)


def test_forward_maintenance_apply_and_recovery_reuse_atomic_caddy_controller(ingress):
    origins, config, base, active = ingress
    normal_base = base.read_bytes()
    base.write_text('https://192.0.2.10 {\n  header Cache-Control "no-store"\n'
                    '  respond "maintenance" 503\n}\n', encoding='utf-8')
    caddy = ObservedCaddy()
    calls = []
    controller = IpIngressController(origins, config, base, active, caddy,
        probe=lambda _routes, _address: calls.append('normal'),
        maintenance_probe=lambda routes, address: calls.append(
            ('maintenance', len(routes), address)), probe_budget_seconds=0)
    maintenance_digest = controller.maintain()
    maintenance = active.read_bytes()
    assert hashlib.sha256(maintenance).hexdigest() == maintenance_digest
    assert b'reverse_proxy' not in maintenance and maintenance.count(b'  respond ') == 3
    assert calls == [('maintenance', 2, config.address)]
    base.write_bytes(normal_base)
    normal_digest = controller.reconcile()
    assert hashlib.sha256(active.read_bytes()).hexdigest() == normal_digest
    assert active.read_bytes() != maintenance
    assert calls[-1] == 'normal' and caddy.reloads == 2


def test_forward_maintenance_probe_failure_restores_prior_caddyfile(ingress):
    origins, config, base, active = ingress
    before = active.read_bytes()
    base.write_text('https://192.0.2.10 {\n  respond "maintenance" 503\n}\n',
                    encoding='utf-8')
    caddy = ObservedCaddy()
    controller = IpIngressController(origins, config, base, active, caddy,
        maintenance_probe=lambda _routes, _address: (_ for _ in ())
            .throw(IngressError('maintenance_probe_mismatch')),
        probe_budget_seconds=0)
    with pytest.raises(IngressError, match='ingress_apply_failed'):
        controller.maintain()
    assert active.read_bytes() == before
    assert caddy.reloads == 2


def test_forward_base_transition_switches_console_and_origins_together(ingress):
    origins, config, base, active = ingress
    normal_base = base.read_bytes()
    maintenance_base = (b'https://192.0.2.10 {\n'
                        b'  header Cache-Control "no-store"\n'
                        b'  respond "maintenance" 503\n}\n')
    caddy = ObservedCaddy()
    calls = []
    controller = IpIngressController(origins, config, base, active, caddy,
        probe=lambda _routes, _address: calls.append('normal'),
        maintenance_probe=lambda _routes, _address: calls.append('maintenance'),
        probe_budget_seconds=0)
    controller.transition_base(maintenance_base, maintenance=True)
    assert base.read_bytes() == maintenance_base
    assert b'reverse_proxy' not in active.read_bytes()
    controller.transition_base(normal_base, maintenance=False)
    assert base.read_bytes() == normal_base
    assert b'reverse_proxy' in active.read_bytes()
    assert calls == ['maintenance', 'normal'] and caddy.reloads == 2


@pytest.mark.parametrize('failure', ['base_write', 'probe'])
def test_failed_base_transition_restores_both_files(ingress, monkeypatch, failure):
    origins, config, base, active = ingress
    original_base, original_active = base.read_bytes(), active.read_bytes()
    maintenance_base = b'https://192.0.2.10 { respond "maintenance" 503 }\n'
    real_replace = controller_module._replace
    if failure == 'base_write':
        def fault_after_base(path, payload, mode):
            real_replace(path, payload, mode)
            if path == base and payload == maintenance_base:
                raise OSError('injected fsync failure after base rename')
        monkeypatch.setattr(controller_module, '_replace', fault_after_base)
    caddy = ObservedCaddy()
    def failing_probe(_routes, _address):
        if failure == 'probe':
            raise IngressError('injected probe failure')
    controller = IpIngressController(origins, config, base, active, caddy,
        maintenance_probe=failing_probe, probe_budget_seconds=0)
    with pytest.raises(IngressError, match='ingress_apply_failed'):
        controller.transition_base(maintenance_base, maintenance=True)
    assert base.read_bytes() == original_base
    assert active.read_bytes() == original_active
    assert caddy.reloads == (1 if failure == 'base_write' else 2)


@pytest.mark.parametrize('failure', ['mount', 'validation', 'reload', 'probe'])
def test_failed_stage_preserves_previous_caddyfile(ingress, failure):
    origins, config, base, active = ingress
    before = active.read_bytes()
    caddy = ObservedCaddy()
    if failure == 'mount':
        def unavailable(_directory):
            raise IngressError('caddy_directory_bind_required')
        caddy.ensure_directory_bind = unavailable
    if failure == 'validation':
        caddy.fail_validation = True
    if failure == 'reload':
        caddy.fail_reload_at = {1}
    def probe(_routes, _config):
        if failure == 'probe':
            raise IngressError('ingress_probe_mismatch')
    controller = IpIngressController(origins, config, base, active, caddy,
                                      probe=probe, probe_budget_seconds=0)
    with pytest.raises(IngressError):
        controller.reconcile()
    assert active.read_bytes() == before
    assert caddy.reloads == (0 if failure in ('mount', 'validation') else 2)


def test_rollback_reload_failure_is_reported_as_critical(ingress):
    origins, config, base, active = ingress
    before = active.read_bytes()
    caddy = ObservedCaddy()
    caddy.fail_reload_at = {1, 2}
    controller = IpIngressController(origins, config, base, active, caddy,
                                      probe=lambda _routes, _config: None,
                                      probe_budget_seconds=0)
    with pytest.raises(IngressError, match='ingress_rollback_failed'):
        controller.reconcile()
    assert active.read_bytes() == before
    assert caddy.reloads == 2


def test_write_failure_after_atomic_rename_restores_prior_file(ingress, monkeypatch):
    origins, config, base, active = ingress
    before = active.read_bytes()
    real_replace = controller_module._replace
    def fault_after_replace(path, payload, mode):
        real_replace(path, payload, mode)
        if payload != before:
            raise OSError('directory fsync failed after rename')
    monkeypatch.setattr(controller_module, '_replace', fault_after_replace)
    caddy = ObservedCaddy()
    controller = IpIngressController(origins, config, base, active, caddy,
                                      probe=lambda _routes, _config: None,
                                      probe_budget_seconds=0)
    with pytest.raises(IngressError, match='ingress_apply_failed'):
        controller.reconcile()
    assert active.read_bytes() == before
    assert caddy.reloads == 1


def test_refuses_a_symlink_active_file(ingress):
    origins, config, base, active = ingress
    original = active.read_bytes()
    protected = active.parent / 'protected'
    protected.write_bytes(original)
    active.unlink()
    try:
        active.symlink_to(protected)
    except OSError:
        pytest.skip('symlinks unavailable on this host')
    controller = IpIngressController(origins, config, base, active, ObservedCaddy(),
                                      probe=lambda _routes, _config: None)
    with pytest.raises(IngressError, match='ingress_files_required'):
        controller.reconcile()
    assert protected.read_bytes() == original
