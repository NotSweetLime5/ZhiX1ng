from fastapi import APIRouter, Depends

from app.api.dependencies import current_user, runtime
from app.api.responses import ok
from app.schemas import Login, Register
from app.schemas.auth import RefreshInput
from app.services import auth as service

router = APIRouter(tags=["auth"])


@router.post("/auth/register")
async def register(body: Register, rt=Depends(runtime)):
    return ok(await service.register(body=body, rt=rt))


@router.post("/auth/login")
async def login(body: Login, rt=Depends(runtime)):
    return ok(await service.login(body=body, rt=rt))


@router.post("/auth/refresh")
async def refresh(body: RefreshInput, rt=Depends(runtime)):
    return ok(await service.refresh(body=body.model_dump(exclude_unset=True), rt=rt))


@router.post("/auth/logout")
async def logout(user=Depends(current_user), rt=Depends(runtime)):
    return ok(await service.logout(user=user, rt=rt))


@router.get("/me")
async def me(user=Depends(current_user)):
    return ok(await service.me(user=user))
