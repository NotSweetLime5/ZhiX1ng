from typing import Literal

from pydantic import Field

from app.schemas.base import Input


class ProviderInput(Input):
    code: str | None = None
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    status: Literal[0, 1] | None = None


class ModelInput(Input):
    provider_id: int | None = None
    model_name: str | None = None
    alias: str | None = None
    type: Literal["chat", "embedding", "rerank"] | None = None
    context_window: int | None = Field(None, ge=1)
    max_output: int | None = Field(None, ge=1)
    input_price: float | None = Field(None, ge=0)
    output_price: float | None = Field(None, ge=0)
    priority: int | None = None
    capabilities: list[str] | None = None
    is_default: bool | None = None
    status: Literal[0, 1] | None = None


class MCPServerInput(Input):
    name: str | None = None
    transport: Literal["streamable_http", "sse"] | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    status: str | None = None
    last_health_at: str | None = None
    tools_cache: list[dict] | None = None


class MCPCallInput(Input):
    name: str = ""
    args: dict = Field(default_factory=dict)


class A2ARegisterInput(Input):
    base_url: str = ""
    name: str = ""


class A2ATaskInput(Input):
    text: str = ""
