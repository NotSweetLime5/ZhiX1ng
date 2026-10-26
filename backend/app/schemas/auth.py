import re

from pydantic import Field, field_validator

from app.schemas.base import Input


class Login(Input):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Register(Login):
    password: str = Field(min_length=12, max_length=256)
    email: str = Field(min_length=3, max_length=128)

    @field_validator("username", "email", mode="before")
    @classmethod
    def trim_identity(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", value):
            raise ValueError("请提供有效邮箱地址")
        return value


class RefreshInput(Input):
    refresh_token: str = ""
