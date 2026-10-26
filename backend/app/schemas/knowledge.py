from pydantic import Field, model_validator

from app.schemas.base import Input


class KBInput(Input):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    embedding_config_id: int | None = None
    chunk_size: int = Field(512, ge=64, le=8192)
    chunk_overlap: int = Field(64, ge=0)

    @model_validator(mode="after")
    def overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        return self


class RetrieveInput(Input):
    query: str = ""
