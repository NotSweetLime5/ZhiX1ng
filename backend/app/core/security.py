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

    def token_pair(self, user):
        stamp = int(time.time())
        base = {"sub": str(user["id"]), "role": user["role"], "iat": stamp}
        access = jwt.encode(
            {**base, "type": "access", "jti": str(uuid.uuid4()), "exp": stamp + self.cfg.access_ttl},
            self.cfg.jwt_secret,
        )
        refresh = jwt.encode(
            {**base, "type": "refresh", "jti": str(uuid.uuid4()), "exp": stamp + self.cfg.refresh_ttl},
            self.cfg.jwt_secret,
        )
        return {"access_token": access, "refresh_token": refresh, "expires_in": self.cfg.access_ttl}

    async def tokens(self, user):
        pair = self.token_pair(user)
        key = f"{self.cfg.redis_namespace}:refresh:{user['id']}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.sadd(key, pair["refresh_token"])
            pipe.expire(key, self.cfg.refresh_ttl)
            await pipe.execute()
        return pair

    async def refresh(self, token, db, users):
        claims = self.decode(token, "refresh")
        user = await db.get(users, int(claims["sub"]))
        if not user or user["status"] != 1:
            raise jwt.InvalidTokenError("用户不可用")
        pair = self.token_pair(user)
        rotated = await self.redis.eval(
            "if redis.call('SREM', KEYS[1], ARGV[1]) == 0 then return 0 end "
            "redis.call('SADD', KEYS[1], ARGV[2]); "
            "redis.call('EXPIRE', KEYS[1], ARGV[3]); return 1",
            1,
            f"{self.cfg.redis_namespace}:refresh:{claims['sub']}",
            token,
            pair["refresh_token"],
            self.cfg.refresh_ttl,
        )
        if not rotated:
            raise jwt.InvalidTokenError("刷新令牌已失效")
        return pair
