from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog, EventLog

async def audit(db: AsyncSession, actor_user_id, action: str, entity: str, entity_id=None, before=None, after=None, ip=None, user_agent=None):
    db.add(AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id else None,
        before=before,
        after=after,
        ip=ip,
        user_agent=user_agent,
    ))

async def event(db: AsyncSession, user_id, event_name: str, meta=None):
    db.add(EventLog(user_id=user_id, event=event_name, meta=meta or {}))
