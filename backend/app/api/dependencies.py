from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, Request

from app import models as t


def runtime(request: Request):
    return request.app.state.runtime


async def current_user(request: Request, rt=Depends(runtime)):
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "请先登录")
    try:
        claims = rt.security.decode(authorization[7:])
        user = await rt.db.get(t.users, int(claims["sub"]))
        if not user or user["status"] != 1:
            raise jwt.InvalidTokenError()
        return user
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(401, "登录凭证失效") from exc


async def admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


class Paging:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        keyword: str = "",
    ):
        self.values = {"page": page, "page_size": page_size, "keyword": keyword}
