from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from ..deps import CurrentUser, DbSession
from ..models import CreditEntry

router = APIRouter(tags=["usage"])


@router.get("/usage")
def usage(user: CurrentUser, session: DbSession) -> dict[str, object]:
    totals = session.execute(
        select(
            func.coalesce(func.sum(-CreditEntry.delta), 0),
            func.count(CreditEntry.id),
            func.coalesce(func.sum(CreditEntry.input_tokens), 0),
            func.coalesce(func.sum(CreditEntry.output_tokens), 0),
        ).where(CreditEntry.user_id == user.id)
    ).one()

    ledger = session.scalars(
        select(CreditEntry)
        .where(CreditEntry.user_id == user.id)
        .order_by(CreditEntry.created_at.desc())
        .limit(50)
    ).all()

    return {
        "credits": user.credits,
        "spent": int(totals[0]),
        "runs": int(totals[1]),
        "inputTokens": int(totals[2]),
        "outputTokens": int(totals[3]),
        "ledger": [
            {
                "delta": entry.delta,
                "reason": entry.reason,
                "inputTokens": entry.input_tokens,
                "outputTokens": entry.output_tokens,
                "at": entry.created_at.isoformat(),
            }
            for entry in ledger
        ],
    }
