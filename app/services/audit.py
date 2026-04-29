"""
Funções de auditoria e eventos.
audit() e event() apenas enfileiram o objeto na sessão (sem flush/commit).
O commit é responsabilidade do router — isso evita queries extras só para log.

Para logs que não precisam ser síncronos com a resposta, use as versões
_background_* com BackgroundTasks do FastAPI.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog, EventLog


async def audit(
    db: AsyncSession,
    actor_user_id,
    action: str,
    entity: str,
    entity_id=None,
    before=None,
    after=None,
    ip=None,
    user_agent=None,
):
    """Enfileira um AuditLog na sessão atual. Não faz commit."""
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
    """Enfileira um EventLog na sessão atual. Não faz commit."""
    db.add(EventLog(user_id=user_id, event=event_name, meta=meta or {}))


# ── Background task helpers (não bloqueiam a resposta ao cliente) ─────────────

async def _bg_event(user_id, event_name: str, meta: dict):
    """Grava um EventLog em sessão própria — para uso em BackgroundTasks."""
    from app.db.session import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            await event(db, user_id, event_name, meta)
            await db.commit()
    except Exception:
        pass  # log secundário nunca deve derrubar a aplicação


async def _bg_audit(actor_user_id, action: str, entity: str, entity_id=None, before=None, after=None):
    """Grava um AuditLog em sessão própria — para uso em BackgroundTasks."""
    from app.db.session import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            await audit(db, actor_user_id, action, entity, entity_id, before=before, after=after)
            await db.commit()
    except Exception:
        pass
