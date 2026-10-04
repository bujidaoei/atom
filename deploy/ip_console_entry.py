"""Canonical console entry, applied through the existing locked ingress controller."""
from pathlib import Path
import argparse
import json
import re
from urllib.error import HTTPError
from urllib.request import Request

import ip_forward_preflight
import ip_forward_stage
import ip_forward_candidate
import ip_forward_capture
import ip_origin_reconcile
import protected_cutover
from app.ip_ingress import IngressError, _NoRedirect, probe_ip_routes
from urllib.request import build_opener, HTTPSHandler, ProxyHandler
import ssl


ROUTE = "  redir /atom /atom/ 308\n"
MOUNT = "  handle_path /atom/* {\n"


def canonical_base(base: bytes) -> bytes:
    if not isinstance(base, bytes) or not 0 < len(base) <= 1024 * 1024:
        raise ValueError('invalid_console_base')
    text = base.decode('utf-8')
    if text.count(MOUNT) != 1:
        raise ValueError('ambiguous_console_mount')
    entries = re.findall(r'^\s*redir /atom\s+.*$', text, re.MULTILINE)
    if entries:
        if len(entries) == 1 and entries[0].strip() == ROUTE.strip():
            return base
        raise ValueError('conflicting_console_redirect')
    return text.replace(MOUNT, ROUTE + MOUNT, 1).encode('utf-8')


def probe_console(address: str) -> None:
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        response = opener.open(Request(f'https://{address}/atom'), timeout=10)
    except HTTPError as error:
        response = error
    with response:
        if response.status != 308 or response.headers.get('Location') != '/atom/':
            raise IngressError('console_redirect_probe_failed')
    with opener.open(Request(f'https://{address}/atom/'), timeout=10) as response:
        body = response.read(256 * 1024)
        if response.status != 200 or b'id="root"' not in body or b'<script' not in body:
            raise IngressError('console_document_probe_failed')


def apply(config_file: Path, publication_file: Path, revision: str):
    config = protected_cutover.load_config(config_file)
    with protected_cutover.host_lock():
        ip_origin_reconcile._no_interrupted_forward(config)
        active = ip_forward_preflight._inspect_locked(config=config,
            publication_file=publication_file, revision=revision, allow_live_activity=True)
        publication = ip_forward_preflight._publication(publication_file, config,
            active['imageId'], require_template_image=False)
        source = Path(active['candidateDirectory'])
        controller = ip_forward_stage._controller(config=config, publication=publication, source=source)
        original = controller.base.read_bytes()
        updated = canonical_base(original)
        if updated != original:
            backup = source / 'caddy' / 'Caddyfile.base.before-entry-redirect'
            if backup.exists():
                ip_forward_capture._private_path(backup, directory=False)
                if backup.read_bytes() != original:
                    raise ValueError('console_backup_mismatch')
            else:
                ip_forward_candidate._private_bytes(backup, original)
        def probe(routes, address):
            probe_ip_routes(routes, address)
            probe_console(address)
        controller.probe = probe
        digest = controller.transition_base(updated, maintenance=False)
        return {'status': 'console_entry_verified', 'caddySha256': digest,
                'applicationRevision': revision, 'originCount': active['activeOriginCount']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--publication-file', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    print(json.dumps(apply(args.config, args.publication_file, args.revision)))
