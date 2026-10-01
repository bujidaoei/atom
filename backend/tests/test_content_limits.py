import pytest

from app.content_service import ContentLimits


@pytest.mark.parametrize('values', [
    {'active_responses': value} for value in (0, -1, 33, True, 1.5, '1')
] + [
    {field: value} for field in ('send_seconds','drain_seconds','receive_seconds')
    for value in (0, -1, 61, True, float('nan'), float('inf'), '1')
])
def test_invalid_capacity_and_deadline_fail_at_configuration(values):
    with pytest.raises(ValueError, match='invalid_content_limits'):
        ContentLimits(**values)
