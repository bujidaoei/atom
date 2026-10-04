from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy'))
from ip_console_entry import canonical_base

BASE = b"{\n  grace_period 5s\n}\nexample.test {\n  handle_path /atom/* {\n    reverse_proxy app:80\n  }\n  handle {\n    redir /atom/ 302\n  }\n}\n"


def test_exact_entry_redirect_preserves_other_routes_and_is_idempotent():
    updated = canonical_base(BASE)
    assert updated.replace(b'  redir /atom /atom/ 308\n', b'') == BASE
    assert canonical_base(updated) == updated


@pytest.mark.parametrize('base', [b'', BASE + BASE, BASE.replace(b'  handle_path', b'  redir /atom /elsewhere 302\n  handle_path')])
def test_ambiguous_configuration_refused(base):
    with pytest.raises(ValueError):
        canonical_base(base)
