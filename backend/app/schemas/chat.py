from pydantic import Field, field_validator

from app.schemas.base import Input


class ChatInput(Input):
    session_id: str | None = None
    agent_id: int = 0
    model_config_id: int = 0
    content: str = Field(min_length=1, max_length=100000)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value):
        value = "".join(c for c in value if c not in {"\u200b", "\ufeff"} and (ord(c) >= 32 or c in "\n\t"))
        if not value.strip():
            raise ValueError("消息不能为空")
        return value


class SessionUpdate(Input):
    title: str = ""
