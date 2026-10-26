from pydantic import Field

from app.schemas.base import Input


class Login(Input):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Register(Login):
    password: str = Field(min_length=8, max_length=256)
    email: str = Field(min_length=3, max_length=128)


class RefreshInput(Input):
    refresh_token: str = ""
