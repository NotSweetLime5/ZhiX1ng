from fastapi import APIRouter, Depends

from app import models as t
from app.api.dependencies import admin, current_user, runtime
from app.api.responses import ok
from app.schemas.admin import ModelInput, ProviderInput
from app.services import catalog
from app.services import models as service

router = APIRouter(tags=["models"])


@router.get("/models")
async def chat_models(user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.chat_models(user=user, rt=rt))


@router.get("/admin/models/providers", name="list_providers")
async def list_providers(type: str | None = None, user=Depends(admin), rt=Depends(runtime)):
    return ok(await catalog.listing(t.providers, ("code", "name", "base_url"), rt, user, type))


@router.post("/admin/models/providers", name="create_providers")
async def create_providers(body: ProviderInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(
        await catalog.create(
            t.providers, ("code", "name", "base_url"), rt, user, body.model_dump(exclude_unset=True)
        )
    )


@router.put("/admin/models/providers/{ident}", name="update_providers")
async def update_providers(ident: int, body: ProviderInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(
        await catalog.edit(
            t.providers, ("code", "name", "base_url"), rt, user, ident, body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/admin/models/providers/{ident}", name="delete_providers")
async def delete_providers(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await catalog.remove(t.providers, ("code", "name", "base_url"), rt, user, ident))


@router.get("/admin/models", name="list_models")
async def list_configs(type: str | None = None, user=Depends(admin), rt=Depends(runtime)):
    return ok(await catalog.listing(t.models, ("provider_id", "model_name", "alias", "type"), rt, user, type))


@router.post("/admin/models", name="create_models")
async def create_configs(body: ModelInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(
        await catalog.create(
            t.models,
            ("provider_id", "model_name", "alias", "type"),
            rt,
            user,
            body.model_dump(exclude_unset=True),
        )
    )


@router.put("/admin/models/{ident}", name="update_models")
async def update_configs(ident: int, body: ModelInput, user=Depends(admin), rt=Depends(runtime)):
    return ok(
        await catalog.edit(
            t.models,
            ("provider_id", "model_name", "alias", "type"),
            rt,
            user,
            ident,
            body.model_dump(exclude_unset=True),
        )
    )


@router.delete("/admin/models/{ident}", name="delete_models")
async def delete_configs(ident: int, user=Depends(admin), rt=Depends(runtime)):
    return ok(await catalog.remove(t.models, ("provider_id", "model_name", "alias", "type"), rt, user, ident))
