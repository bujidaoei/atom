"""Local policy administration using protected database file authority."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .audit_retention import RetentionError, RetentionRepository


def main(argv=None):
    parser = argparse.ArgumentParser(description='Explicit audit policy and hold administration; never deletes events.')
    parser.add_argument('--database', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('policies','holds'):
        page = commands.add_parser(name)
        page.add_argument('--after', default='')
        page.add_argument('--limit', type=int, default=50)
        if name == 'holds':
            page.add_argument('--policy-id', required=True)
    change = commands.add_parser('apply')
    for name in ('command-id','policy-id','operator-id'):
        change.add_argument('--'+name, required=True)
    change.add_argument('--action', choices=('create_policy','update_policy','place_hold','release_hold'), required=True)
    change.add_argument('--expected-generation', type=int, required=True)
    for name in ('scope-kind','scope-id','event-kind','state','archive-store-id','hold-id','hold-kind'):
        change.add_argument('--'+name)
    change.add_argument('--min-age-seconds', type=int)
    arguments = vars(parser.parse_args(argv))
    try:
        repository = RetentionRepository(arguments.pop('database'))
        operation = arguments.pop('command')
        if operation == 'apply':
            result = {'receipt': asdict(repository.execute(**arguments))}
        else:
            rows = getattr(repository, operation)(**arguments)
            key = 'policy_id' if operation == 'policies' else 'hold_id'
            result = {operation: rows, 'next_after': rows[-1][key] if len(rows) == arguments['limit'] else None}
        print(json.dumps({'ok': True, **result}, separators=(',', ':')))
        return 0
    except RetentionError as error:
        print(json.dumps({'ok': False, 'error': str(error)}, separators=(',', ':')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
