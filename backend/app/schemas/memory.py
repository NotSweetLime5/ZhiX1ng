from app.schemas.base import Input


class MemoryExtractInput(Input):
    session_id: str = ""
