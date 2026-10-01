"""Explicit offline maintenance of one independently verified audit archive."""
import argparse
import json
from pathlib import Path

from .audit_archive import ArchiveError
from .audit_pruning import AuditPruning, PruneError
from .audit_retention import RetentionError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prune one verified archive on an offline schema11 database.')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--store-root', type=Path, required=True)
    for name in ('store-id', 'verifier-id', 'expected-image', 'expected-policy-digest',
                 'command-id', 'operator-id', 'archive-id', 'recovery-id', 'expected-context'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--expected-generation', type=int, required=True)
    values = vars(parser.parse_args(argv))
    try:
        service = AuditPruning(values.pop('database'), root=values.pop('store_root'),
            **{key: values.pop(key) for key in ('store_id', 'verifier_id', 'expected_image', 'expected_policy_digest')})
        receipt = service.prune(**values)
        print(json.dumps(dict(ok=True, receipt=receipt), separators=(',', ':')))
        return 0
    except (ArchiveError, RetentionError, PruneError) as error:
        print(json.dumps(dict(ok=False, error=str(error)), separators=(',', ':')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
