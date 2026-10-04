"""Capture only generation policy from a private project .env before cutover."""
from pathlib import Path
import re

from ip_cutover_env import EnvironmentError, _private_file

KEYS = frozenset({'ATOM_BUILD_BUDGET_SECONDS', 'ATOM_RUN_TIMEOUT_SECONDS',
                  'ATOM_LLM_TIMEOUT_SECONDS'})


def validate(values: dict[str, str]) -> dict[str, str]:
    if set(values) - KEYS or any(not isinstance(value, str) or
            re.fullmatch(r'[1-9][0-9]{0,3}', value) is None or
            int(value) > 7140 for value in values.values()):
        raise EnvironmentError('invalid_generation_settings')
    budgets = [int(values.get(key, '3600')) for key in
               ('ATOM_BUILD_BUDGET_SECONDS', 'ATOM_RUN_TIMEOUT_SECONDS')]
    if int(values.get('ATOM_LLM_TIMEOUT_SECONDS', str(max(budgets)))) < max(budgets):
        raise EnvironmentError('model_timeout_shorter_than_generation')
    return dict(values)


def capture(source: Path, existing: dict[str, str]) -> dict[str, str]:
    values = {key: value for key, value in existing.items() if key in KEYS}
    path = source / '.env'
    if path.is_symlink():
        raise EnvironmentError('generation_settings_symlink')
    if path.exists():
        configured = _private_file(path)
        values.update({key: value for key, value in configured.items() if key in KEYS})
    return validate(values)
