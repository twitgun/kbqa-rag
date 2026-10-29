"""答案反馈接口（API-16，FR-31/32）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from kbqa.api.deps import get_db
from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.api.response import ok
from kbqa.infra.db import models as m

router = APIRouter(prefix="/feedback", tags=["feedback"])

REASONS = {"unsupported", "no_answer", "wrong_citation", "outdated", "other"}


@router.post("")
def submit_feedback(body: dict, db: Session = Depends(get_db)) -> dict:
    qa_id = body.get("qa_id")
    rating = body.get("rating")
    reason = body.get("reason_code")
    comment = (body.get("comment") or "").strip()[:500]

    if not isinstance(qa_id, int):
        raise ApiError(ErrorCode.INVALID_PARAM, "qa_id 必须是整数")
    if rating not in (1, -1):
        raise ApiError(ErrorCode.INVALID_PARAM, "rating 只能是 1 或 -1")
    if rating == 1 and reason:
        raise ApiError(ErrorCode.INVALID_PARAM, "点赞时无需填写错因")
    if rating == -1 and not reason:
        reason = "other"
    if reason and reason not in REASONS:
        raise ApiError(ErrorCode.INVALID_PARAM, f"错因只能是 {sorted(REASONS)}")

    if db.get(m.QaRecord, qa_id) is None:
        raise ApiError(ErrorCode.QA_NOT_FOUND, "问答记录不存在")

    row = db.scalar(select(m.Feedback).where(m.Feedback.qa_id == qa_id))
    if row:
        row.rating = rating
        row.reason_code = reason
        row.comment = comment
        action = "updated"
    else:
        row = m.Feedback(qa_id=qa_id, rating=rating, reason_code=reason, comment=comment)
        db.add(row)
        action = "created"
    db.commit()
    return ok({"feedback_id": row.id, "action": action})
