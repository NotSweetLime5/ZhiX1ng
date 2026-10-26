from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class GraphState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    expert: int
    plan: list[dict]
    results: list[dict]
    index: int
    replans: int
    failure: str
