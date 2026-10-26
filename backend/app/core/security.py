import base64
import hashlib
import os
import time
import uuid

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pwdlib import PasswordHash

passwords = PasswordHash.recommended()


class Security:
    def __init__(self, cfg, redis):
        self.cfg, self.redis = cfg, redis
        self.cipher = AESGCM(hashlib.sha256(cfg.secret_key.encode()).digest())

    def encrypt(self, value):
        if not value:
            return ""
        nonce = os.urandom(12)
        return base64.b64encode(nonce + self.cipher.encrypt(nonce, value.encode(), None)).decode()

    def decrypt(self, value):
        if not value:
            return ""
        raw = base64.b64decode(value)
        return self.cipher.decrypt(raw[:12], raw[12:], None).decode()

    def decode(self, token, kind="access"):
        claims = jwt.decode(
            token, self.cfg.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub", "type"]}
        )
        if claims["type"] != kind:
            raise jwt.InvalidTokenError("错误的令牌类型")
        return claims

    async def tokens(self, user):
        stamp = int(time.time())
        base = {"sub": str(user["id"]), "role": user["role"], "iat": stamp}
        access = jwt.encode(
            {**base, "type": "access", "exp": stamp + self.cfg.access_ttl}, self.cfg.jwt_secret
        )
        refresh = jwt.encode(
            {**base, "type": "refresh", "jti": str(uuid.uuid4()), "exp": stamp + self.cfg.refresh_ttl},
            self.cfg.jwt_secret,
        )
        key = f"nx:refresh:{user['id']}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.sadd(key, refresh)
            pipe.expire(key, self.cfg.refresh_ttl)
            await pipe.execute()
        return {"access_token": access, "refresh_token": refresh, "expires_in": self.cfg.access_ttl}

    async def refresh(self, token, db, users):
        claims = self.decode(token, "refresh")
        if not await self.redis.sismember(f"nx:refresh:{claims['sub']}", token):
            raise jwt.InvalidTokenError("刷新令牌已失效")
        user = await db.get(users, int(claims["sub"]))
        if not user or user["status"] != 1:
            raise jwt.InvalidTokenError("用户不可用")
        # Keep the old token valid until expiry, so concurrent tabs can refresh safely.
        return await self.tokens(user)
