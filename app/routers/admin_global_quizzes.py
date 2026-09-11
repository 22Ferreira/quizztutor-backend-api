from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.utils.rbac import require_roles, get_current_user
from app.models import User, Quiz
from app.models.global_quiz import GlobalQuizRequest, GlobalQuizRequestStatus
from app.schemas.global_quizzes import GlobalQuizListItem, AdminReviewIn
from app.services.audit import audit

router = APIRouter(prefix="/admin/global-quiz-requests", tags=["admin-global-quizzes"], dependencies=[Depends(require_roles("ADMIN"))])

def _make_slug(title: str, req_id: str) -> str:
    base = "".join([c.lower() if c.isalnum() else "-" for c in (title or "")]).strip("-")
    while "--" in base:
        base = base.replace("--","-")
    base = base[:35] if base else "quiz"
    return f"{base}-{req_id[:8]}"

@router.get("")
async def list_requests(status: str = "PENDING", db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    st = status.upper()
    q = await db.execute(select(GlobalQuizRequest).where(GlobalQuizRequest.status == st))
    reqs = q.scalars().all()
    if not reqs:
        return []

    # Sem isso o admin via só um ID de request — nem o título do quiz nem
    # quem pediu, tendo que aprovar/rejeitar "às cegas".
    requester_ids = {r.requested_by for r in reqs if r.requested_by}
    names_by_id: dict = {}
    if requester_ids:
        uq = await db.execute(select(User).where(User.id.in_(requester_ids)))
        names_by_id = {u.id: u.name for u in uq.scalars().all()}

    return [
        {
            "id": str(r.id),
            "quiz_id": str(r.quiz_id),
            "quiz_title": r.quiz.title if r.quiz else None,
            "status": r.status,
            "requested_at": r.requested_at,
            "requested_by_name": names_by_id.get(r.requested_by),
            "is_active": r.is_active,
        }
        for r in reqs
    ]

@router.post("/{request_id}/approve")
async def approve(request_id: str, payload: AdminReviewIn, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(GlobalQuizRequest).where(GlobalQuizRequest.id == request_id))
    req = q.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request não encontrado")
    quiz_q = await db.execute(select(Quiz).where(Quiz.id == req.quiz_id))
    quiz = quiz_q.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    req.status = GlobalQuizRequestStatus.APPROVED
    req.is_active = True
    req.review_note = payload.review_note
    req.reviewed_by = me.id
    req.reviewed_at = datetime.now(timezone.utc)
    if not req.approved_public_slug:
        req.approved_public_slug = _make_slug(quiz.title, str(req.id))
    await audit(db, me.id, "GLOBAL_PUBLISH_APPROVED", "GlobalQuizRequest", req.id, after={"status":"APPROVED","slug":req.approved_public_slug})
    await db.commit()
    return {"status": req.status, "slug": req.approved_public_slug}

@router.post("/{request_id}/reject")
async def reject(request_id: str, payload: AdminReviewIn, db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    q = await db.execute(select(GlobalQuizRequest).where(GlobalQuizRequest.id == request_id))
    req = q.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request não encontrado")
    if not payload.review_note:
        raise HTTPException(status_code=400, detail="review_note obrigatório para rejeitar")
    req.status = GlobalQuizRequestStatus.REJECTED
    req.is_active = False
    req.review_note = payload.review_note
    req.reviewed_by = me.id
    req.reviewed_at = datetime.now(timezone.utc)
    await audit(db, me.id, "GLOBAL_PUBLISH_REJECTED", "GlobalQuizRequest", req.id, after={"status":"REJECTED"})
    await db.commit()
    return {"status": req.status}
