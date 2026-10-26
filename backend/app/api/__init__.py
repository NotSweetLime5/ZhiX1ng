from fastapi import APIRouter

from app.api.routes import (
    agents,
    auth,
    chat,
    evaluation,
    integrations,
    jobs,
    knowledge,
    memories,
    models,
    workflows,
)

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(chat.router)
router.include_router(agents.router)
router.include_router(memories.router)
router.include_router(knowledge.router)
router.include_router(workflows.router)
router.include_router(models.router)
router.include_router(integrations.router)
router.include_router(evaluation.router)
router.include_router(jobs.router)
