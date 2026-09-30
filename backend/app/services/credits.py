from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..errors import OutOfCredits
from ..models import CreditEntry, User

# One agent turn costs one credit, whichever role runs it. Atoms prices by
# task complexity; a flat rate is honest for a demo and keeps the ledger
# readable.
TURN_COST = 1


def ensure_affordable(session: Session, user: User, turns: int = 1) -> None:
    if user.credits < TURN_COST * turns:
        raise OutOfCredits(
            f"额度不足，还需要 {TURN_COST * turns - user.credits} credit"
        )


def charge(
    session: Session,
    user_id: str,
    *,
    reason: str,
    run_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    turns: int = 1,
) -> None:
    if (
        run_id
        and session.scalar(
            select(CreditEntry.id).where(CreditEntry.run_id == run_id).limit(1)
        )
        is not None
    ):
        return
    user = session.get(User, user_id)
    if user is None:
        return
    amount = TURN_COST * turns
    user.credits = max(0, user.credits - amount)
    session.add(
        CreditEntry(
            user_id=user_id,
            delta=-amount,
            reason=reason,
            run_id=run_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )
