"""Explicit local archive operations; protected filesystem authority, no tenant endpoint."""
import argparse
import json
from pathlib import Path

from .audit_archive import ArchiveError
from .audit_archiving import AuditArchiving
from .audit_retention import RetentionError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Publish, inspect or recover audit archives; never deletes events.')
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--store-id',required=True)
    parser.add_argument('--store-root',type=Path,required=True)
    commands = parser.add_subparsers(dest='command',required=True)
    archive = commands.add_parser('archive')
    for name in ('archive-id','operator-id','policy-id'):
        archive.add_argument('--'+name,required=True)
    archive.add_argument('--expected-generation',type=int,required=True)
    archive.add_argument('--after',type=int,default=0)
    archive.add_argument('--upper',type=int)
    archive.add_argument('--expected-context')
    recovery = commands.add_parser('recover')
    for name in ('archive-id','recovery-id','verifier-id'):
        recovery.add_argument('--'+name,required=True)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('--archive-id',required=True)
    values = vars(parser.parse_args(argv))
    operation = values.pop('command')
    try:
        service = AuditArchiving(values.pop('database'),store_id=values.pop('store_id'),root=values.pop('store_root'))
        if operation == 'archive':
            service.archive(**values)
            result = service.inspect(archive_id=values['archive_id'])
        elif operation == 'recover':
            result = dict(receipt=service.recover(**values),deletion_authorized=False)
        else:
            result = service.inspect(**values)
        print(json.dumps(dict(ok=True,**result),separators=(',',':')))
        return 0
    except (ArchiveError, RetentionError) as error:
        print(json.dumps(dict(ok=False,error=str(error)),separators=(',',':')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
