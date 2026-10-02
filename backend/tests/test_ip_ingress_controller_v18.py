"""Atomic ingress file application and failure recovery against a real ledger."""
import hashlib

import pytest

from app import ip_ingress_controller as controller_module
from app.ip_ingress import IngressError, IpIngressConfig, render_ip_caddyfile
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
    assert caddy.reloads == 1 and observed == [(origins.active_routes(), config)]
    # A restart must reapply even if the config bytes have not changed.
    assert controller.reconcile() == digest
    assert caddy.reloads == 2 and len(observed) == 2


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
