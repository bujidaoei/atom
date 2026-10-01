"""Local trusted-operator CLI; access follows protected database file authority."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .audit_governance import AuditGovernanceError, AuditGovernanceRepository


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inspect or explicitly govern persisted audit destinations.')
    parser.add_argument('--database', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list')
    listing.add_argument('--after', default='')
    listing.add_argument('--limit', type=int, default=50)
    change = commands.add_parser('apply')
    change.add_argument('--command-id', required=True)
    change.add_argument('--operator-id', required=True)
    change.add_argument('--destination-id', required=True)
    change.add_argument('--scope-kind', choices=('account', 'project'), required=True)
    change.add_argument('--scope-id', required=True)
    change.add_argument('--action', choices=('register', 'suspend', 'resume', 'block', 'retire'), required=True)
    change.add_argument('--expected-generation', type=int, required=True)
    change.add_argument('--reason', choices=('receiver_configuration', 'invalid_payload'))
    arguments = vars(parser.parse_args(argv))
    try:
        repository = AuditGovernanceRepository(arguments.pop('database'))
        operation = arguments.pop('command')
        if operation == 'list':
            rows = repository.page(**arguments)
            # A full page is not proof of exhaustion; continue from the last id.
            result = {'destinations': rows, 'next_after': rows[-1]['destination_id'] if len(rows) == arguments['limit'] else None}
        else:
            result = {'receipt': asdict(repository.execute(**arguments))}
        print(json.dumps({'ok': True, **result}, separators=(',', ':')))
        return 0
    except AuditGovernanceError as error:
        print(json.dumps({'ok': False, 'error': str(error)}, separators=(',', ':')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
