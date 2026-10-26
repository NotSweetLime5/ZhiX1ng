from typing import Literal

from pydantic import Field

from app.schemas.base import Input


class WorkflowInput(Input):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    dsl: str = Field(min_length=1, max_length=200000)
    is_active: bool = True


class WorkflowUpdate(Input):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    dsl: str | None = Field(None, min_length=1, max_length=200000)
    is_active: bool | None = None
    status: Literal[0, 1] | None = None


class RunInput(Input):
    workflow_id: int
    input: dict = Field(default_factory=dict)


class Approval(Input):
    approved: bool
    comment: str = ""


class WorkflowValidationInput(Input):
    dsl: str = ""
