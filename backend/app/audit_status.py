"""Read-only process-operator audit backlog inspection; no remote contact or secret output."""
import argparse
import json

from .audit_delivery import AuditDeliveryRepository, AuditDeliveryError
from .config import get_settings


def collect_status(settings):
    destinations = settings.audit_destinations
    rows = []
    for destination in destinations:
        try:
            values = AuditDeliveryRepository(settings.db_path, destination_id=destination.destination_id,
                scope_kind=destination.scope_kind, scope_id=destination.scope_id).status()
            rows.append({'destination_id': destination.destination_id, 'ok': True, **values})
        except AuditDeliveryError:
            rows.append({'destination_id': destination.destination_id, 'ok': False,
                         'error': 'audit_status_unavailable'})
    return {'schema_version': 1, 'enabled': bool(destinations),
            'ok': all(row['ok'] for row in rows), 'destinations': rows}


def main():
    parser = argparse.ArgumentParser(description='Inspect configured audit delivery backlog without sending events.')
    parser.add_argument('--require-drained', action='store_true',
                        help='Exit 2 when export is disabled or any configured scope has unconfirmed events.')
    arguments = parser.parse_args()
    try:
        result = collect_status(get_settings())
    except Exception:
        result = {'schema_version': 1, 'ok': False, 'error': 'audit_configuration_unavailable'}
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    if not result['ok']:
        return 1
    if arguments.require_drained and (not result['enabled'] or any(row['backlog'] for row in result['destinations'])):
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
