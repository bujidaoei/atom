from sqlalchemy import select

from app.db import session_scope
from app.models import CreditEntry, User
from app.services.credits import charge


def test_terminal_reconciliation_cannot_charge_same_run_twice(signed_in):
    with session_scope() as session:
        user = session.scalar(select(User))
        user_id, before = user.id, user.credits
        charge(session, user_id, reason="build", run_id="same-run", input_tokens=42)
    with session_scope() as session:
        charge(
            session, user_id, reason="interrupted", run_id="same-run", input_tokens=42
        )
    with session_scope() as session:
        assert session.get(User, user_id).credits == before - 1
        entries = list(
            session.scalars(select(CreditEntry).where(CreditEntry.run_id == "same-run"))
        )
        assert len(entries) == 1 and entries[0].input_tokens == 42
