from pydantic import Field

from app.schemas.base import Input


class ChatInput(Input):
    session_id: str | None = None
    agent_id: int = 0
    model_config_id: int = 0
    content: str = Field(min_length=1, max_length=100000)


class SessionUpdate(Input):
    title: str = ""
