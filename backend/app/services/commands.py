"""Durable replay receipts for the single-worker command dispatcher.

Routes check replay before guards and record after non-yielding job registration.
No gateway or tool execution takes place in the request transaction.
"""

import hashlib
import json

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..models import CommandReceipt


class Command:
    def __init__(
        self,
        session: Session,
        project_id: str,
        request: Request,
        action: str,
        body=None,
    ):
        self.session, self.project_id = session, project_id
        self.key = request.headers.get("Idempotency-Key")
        if self.key is not None and (not self.key.strip() or len(self.key) > 128):
            raise HTTPException(400, "Idempotency-Key 必须为 1–128 个字符")
        self.digest = hashlib.sha256(
            json.dumps([action, body], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def replay(self):
        if self.key is None:
            return None
        receipt = self.session.get(CommandReceipt, (self.project_id, self.key))
        if receipt is None:
            return None
        if receipt.digest != self.digest:
            raise HTTPException(409, "该请求标识已用于不同操作，请重新发起")
        return json.loads(receipt.response_json)

    def save(self, response):
        if self.key is not None:
            self.session.add(
                CommandReceipt(
                    project_id=self.project_id,
                    key=self.key,
                    digest=self.digest,
                    response_json=json.dumps(response, ensure_ascii=False),
                )
            )
            self.session.commit()
        return response
