"""Apply committed project origins to a directory-mounted Caddy configuration.

The ledger is authoritative. An interrupted run is repaired by rerunning this
command on service startup; it never infers an origin from a release URL.
"""
from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
import time

from .ip_ingress import IngressError, IpIngressConfig, probe_ip_routes, render_ip_routes
from .project_origins import ProjectOriginRepository


@contextmanager
def _exclusive(path: Path):
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b'\0')
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == 'nt':
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _replace(path: Path, payload: bytes, mode: int):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.atom-caddy-',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, mode)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DockerCaddy:
    """Fixed-argv Caddy adapter; no shell or generated configuration in logs."""

    def __init__(self, container: str, caddyfile: str):
        if (not isinstance(container, str) or not container
                or not all(character.isalnum() or character in '._-' for character in container)
                or not isinstance(caddyfile, str) or
                PurePosixPath(caddyfile) != PurePosixPath('/etc/caddy/Caddyfile')):
            raise IngressError('invalid_caddy_target')
        self.container, self.caddyfile = container, caddyfile

    def ensure_directory_bind(self, directory: Path):
        try:
            result = subprocess.run(['docker', 'inspect', '--format', '{{json .Mounts}}',
                                     self.container], capture_output=True, timeout=10, check=True)
            mounts = json.loads(result.stdout)
        except (subprocess.SubprocessError, OSError, ValueError):
            raise IngressError('caddy_mount_unavailable') from None
        if (type(mounts) is not list or not any(
                type(mount) is dict and mount.get('Type') == 'bind'
                and mount.get('Destination') == '/etc/caddy'
                and mount.get('RW') is False
                and isinstance(mount.get('Source'), str)
                and Path(mount['Source']).resolve() == directory.resolve()
                for mount in mounts)):
            raise IngressError('caddy_directory_bind_required')

    def validate(self, candidate: bytes):
        try:
            result = subprocess.run(['docker', 'exec', '-i', self.container, 'caddy',
                                     'adapt', '--config', '-', '--adapter', 'caddyfile'],
                                    input=candidate, capture_output=True, timeout=30)
        except (subprocess.SubprocessError, OSError):
            raise IngressError('caddy_validation_unavailable') from None
        if result.returncode != 0:
            raise IngressError('caddy_validation_failed')

    def reload(self):
        try:
            result = subprocess.run(['docker', 'exec', self.container, 'caddy',
                                     'reload', '--config', self.caddyfile,
                                     '--adapter', 'caddyfile'], capture_output=True,
                                    timeout=30)
        except (subprocess.SubprocessError, OSError):
            raise IngressError('caddy_reload_unavailable') from None
        if result.returncode != 0:
            raise IngressError('caddy_reload_failed')


class IpIngressController:
    def __init__(self, repository: ProjectOriginRepository, config: IpIngressConfig,
                 base: Path, active: Path, caddy: DockerCaddy, *,
                 probe=probe_ip_routes, probe_budget_seconds: float = 90):
        if (not isinstance(repository, ProjectOriginRepository)
                or not isinstance(config, IpIngressConfig)
                or not isinstance(base, Path) or not isinstance(active, Path)
                or not base.is_absolute() or not active.is_absolute()
                or base == active or base.parent != active.parent
                or not isinstance(caddy, DockerCaddy)
                or not callable(probe)
                or isinstance(probe_budget_seconds, bool)
                or not isinstance(probe_budget_seconds, (int, float))
                or not 0 <= probe_budget_seconds <= 300):
            raise IngressError('invalid_ingress_controller')
        self.repository, self.config = repository, config
        self.base, self.active, self.caddy = base, active, caddy
        self.probe, self.probe_budget_seconds = probe, probe_budget_seconds

    def reconcile(self) -> str:
        """Validate, replace, reload and probe; restore prior bytes on failure.

        A second run always reloads and probes, even when bytes match, so a
        process restart repairs a missing listener. New ledger rows that appear
        during application trigger another pass under the same host lock.
        """
        with _exclusive(self.active.parent / '.atom-ingress.lock'):
            self.caddy.ensure_directory_bind(self.active.parent)
            for _attempt in range(3):
                if (not self.base.is_file() or not self.active.is_file()
                        or self.base.is_symlink() or self.active.is_symlink()):
                    raise IngressError('ingress_files_required')
                original = self.active.read_bytes()
                base = self.base.read_bytes()
                if len(base) > 1024 * 1024 or len(original) > 1024 * 1024:
                    raise IngressError('ingress_file_too_large')
                try:
                    base_text = base.decode('utf-8')
                except UnicodeError:
                    raise IngressError('invalid_base_caddyfile') from None
                routes = self.repository.active_routes()
                candidate = render_ip_routes(base_text, routes, self.config).encode('utf-8')
                mode = stat.S_IMODE(self.active.stat().st_mode)
                self.caddy.validate(candidate)
                # _replace can fail after os.replace (for example during the
                # directory fsync), so every attempted write needs recovery.
                replaced = True
                try:
                    _replace(self.active, candidate, mode)
                    self.caddy.reload()
                    deadline = time.monotonic() + self.probe_budget_seconds
                    while True:
                        try:
                            self.probe(routes, self.config)
                            break
                        except IngressError:
                            if time.monotonic() >= deadline:
                                raise
                            time.sleep(min(1, deadline - time.monotonic()))
                except BaseException as failure:
                    if replaced:
                        try:
                            _replace(self.active, original, mode)
                            self.caddy.reload()
                        except BaseException:
                            raise IngressError('ingress_rollback_failed') from failure
                    raise IngressError('ingress_apply_failed') from failure
                if self.repository.active_routes() == routes:
                    return hashlib.sha256(candidate).hexdigest()
            raise IngressError('ingress_ledger_moving')


def main() -> int:
    parser = argparse.ArgumentParser(description='Reconcile Caddy with committed Atom IP origins')
    for name in ('db', 'base', 'active', 'address', 'preview-upstream',
                 'public-upstream', 'acme-directory', 'container'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--first-port', type=int, required=True)
    parser.add_argument('--last-port', type=int, required=True)
    arguments = parser.parse_args()
    repository = ProjectOriginRepository(Path(arguments.db), first_port=arguments.first_port,
                                         last_port=arguments.last_port)
    config = IpIngressConfig(arguments.address, arguments.preview_upstream,
                             arguments.public_upstream, arguments.acme_directory)
    controller = IpIngressController(repository, config, Path(arguments.base),
        Path(arguments.active), DockerCaddy(arguments.container, '/etc/caddy/Caddyfile'))
    print(controller.reconcile())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
