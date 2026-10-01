"""Strict process-operator configuration; never accept this input from tenant requests."""
import json

from .audit_destination import AuditDestination, AuditDestinationError


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def audit_destinations(value):
    try:
        if not isinstance(value, str) or not value.isascii() or len(value) > 32768:
            raise ValueError
        rows = json.loads(value, object_pairs_hook=_unique)
        if type(rows) is not list or len(rows) > 4:
            raise ValueError
        result = []
        for row in rows:
            if (type(row) is not dict or set(row) != {'host', 'path', 'addresses', 'scope_kind', 'scope_id', 'token'}
                    or type(row['addresses']) is not list):
                raise ValueError
            result.append(AuditDestination(**(row | {'addresses': tuple(row['addresses'])})))
        if len({item.destination_id for item in result}) != len(result):
            raise ValueError
        return tuple(result)
    except (ValueError, TypeError, RecursionError, AuditDestinationError):
        raise ValueError('invalid_audit_export_configuration') from None
