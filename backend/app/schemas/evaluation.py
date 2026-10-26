from pydantic import Field

from app.schemas.base import Input


class DatasetInput(Input):
    name: str = ""
    description: str = ""
    scene: str = "agent"


class CaseInput(Input):
    question: str = ""
    expected_answer: str = ""
    expected_tools: list[str] = Field(default_factory=list)
    expected_chunk_ids: list[int] = Field(default_factory=list)


class EvalRunInput(Input):
    dataset_id: int = 0
    agent_id: int = 0
