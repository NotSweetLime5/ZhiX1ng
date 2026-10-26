from app import models as t
from app.agents.workflow import parse_dsl
from app.services.access import owned


async def validate_workflow(user, body):
    parse_dsl(body.get("dsl", ""))
    return {"valid": True}


async def run_workflow(rt, user, body):
    workflow = await owned(rt, t.workflows, body.workflow_id, user, "creator_id")
    return await rt.workflow.run(workflow, user, body.input)


async def list_runs(rt, user, paging, workflow_id=None):
    filters = [t.runs.c.user_id == user["id"]]
    if workflow_id:
        filters.append(t.runs.c.workflow_id == workflow_id)
    return await rt.db.paged(t.runs, *filters, **paging)


async def get_run(rt, user, ident):
    run = await owned(rt, t.runs, ident, user)
    run["steps"] = await rt.db.rows(t.steps, t.steps.c.run_id == ident, ascending=True)
    return run


async def approve(rt, user, ident, body):
    run = await owned(rt, t.runs, ident, user)
    return await rt.workflow.approve(run, user, body.model_dump())


async def list_workflows(rt, user, paging):
    return await rt.db.paged(t.workflows, t.workflows.c.creator_id == user["id"], **paging)


async def create_workflow(rt, user, body):
    parse_dsl(body.dsl)
    return await rt.db.add(t.workflows, {**body.model_dump(), "creator_id": user["id"]})


async def get_workflow(rt, user, ident):
    return await owned(rt, t.workflows, ident, user, "creator_id")


async def update_workflow(rt, user, ident, body):
    current = await owned(rt, t.workflows, ident, user, "creator_id")
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    if "dsl" in values:
        dsl = parse_dsl(values["dsl"])
        values.setdefault("name", dsl["name"])
        values.setdefault("description", dsl.get("desc", ""))
    return await rt.db.change(t.workflows, ident, {**values, "version": current["version"] + 1})


async def delete_workflow(rt, user, ident):
    await owned(rt, t.workflows, ident, user, "creator_id")
    runs = await rt.db.rows(t.runs, t.runs.c.workflow_id == ident, limit=100000)
    for run in runs:
        await rt.checkpointer.adelete_thread(f"workflow:{run['id']}")
    await rt.db.remove(t.workflows, ident)
    return None
