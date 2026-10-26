from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.base import Input


class AgentInput(Input):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    type: Literal["host", "expert"] | None = None
    system_prompt: str | None = None
    model_config_id: int | None = None
    fallback_model_config_id: int | None = None
    temperature: float | None = Field(None, ge=0, le=2)
    top_p: float | None = Field(None, ge=0, le=1)
    max_tokens: int | None = Field(None, ge=1, le=128000)
    max_iterations: int | None = Field(None, ge=1, le=50)
    memory_enabled: bool | None = None
    memory_window: int | None = Field(None, ge=1, le=100)
    memory_long_enabled: bool | None = None
    kb_ids: list[int] | None = None
    tools: list[dict] | None = None
    config: dict | None = None
    status: Literal[0, 1] | None = None


class PlanStep(BaseModel):
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    goal: str
    steps: list[PlanStep] = Field(min_length=1, max_length=6)
