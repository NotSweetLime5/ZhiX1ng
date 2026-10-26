import time

from sqlalchemy import delete, insert

from app import models as t
from app.agents.planning import content_text
from app.services.access import owned


async def datasets(rt, user):
    return await rt.db.rows(t.eval_datasets, t.eval_datasets.c.user_id == user["id"])


async def create_dataset(rt, user, body):
    if not body.get("name"):
        raise ValueError("name 必填")
    return await rt.db.add(
        t.eval_datasets,
        {
            "name": body["name"],
            "description": body.get("description", ""),
            "user_id": user["id"],
            "scene": body.get("scene", "agent"),
        },
    )


async def cases(rt, user, ident):
    await owned(rt, t.eval_datasets, ident, user)
    return await rt.db.rows(t.eval_cases, t.eval_cases.c.dataset_id == ident)


async def create_case(rt, user, ident, body):
    dataset = await owned(rt, t.eval_datasets, ident, user)
    if not body.get("question"):
        raise ValueError("question 必填")
    case = await rt.db.add(
        t.eval_cases,
        {
            "dataset_id": ident,
            "question": body["question"],
            "expected_answer": body.get("expected_answer", ""),
            "expected_tools": body.get("expected_tools", []),
            "expected_chunk_ids": body.get("expected_chunk_ids", []),
        },
    )
    await rt.db.change(t.eval_datasets, ident, {"case_count": dataset["case_count"] + 1})
    return case


async def create_run(rt, user, body):
    await owned(rt, t.eval_datasets, body.get("dataset_id", 0), user)
    await rt.agent.load(body.get("agent_id", 0), user)
    async with rt.db.engine.begin() as conn:
        run = (
            (
                await conn.execute(
                    insert(t.eval_runs)
                    .values(
                        dataset_id=body["dataset_id"],
                        user_id=user["id"],
                        agent_id=body.get("agent_id") or None,
                    )
                    .returning(t.eval_runs)
                )
            )
            .mappings()
            .one()
        )
        await conn.execute(insert(t.jobs).values(kind="eval", payload={"run_id": run["id"]}))
    return dict(run)


async def get_eval_run(rt, user, ident):
    run = await owned(rt, t.eval_runs, ident, user)
    run["results"] = await rt.db.rows(t.eval_results, t.eval_results.c.run_id == ident)
    return run


async def evaluate(rt, run_id):
    run = await rt.db.get(t.eval_runs, run_id)
    if not run:
        return
    await rt.db.change(t.eval_runs, run_id, {"status": "running"})
    user = await rt.db.get(t.users, run["user_id"])
    agent = await rt.agent.load(run["agent_id"] or 0, user)
    cases = await rt.db.rows(t.eval_cases, t.eval_cases.c.dataset_id == run["dataset_id"], limit=10000)
    passed = 0
    async with rt.db.engine.begin() as conn:
        await conn.execute(delete(t.eval_results).where(t.eval_results.c.run_id == run_id))
    for case in cases:
        start = time.monotonic()
        output = {}
        error = ""
        refs = []
        try:
            system, refs, messages = await rt.agent.context(
                agent, user, case["question"], [{"role": "user", "content": case["question"]}]
            )
            graph = await rt.agent.compile(agent, user, system)
            async for _ in rt.agent.events(graph, messages, f"eval:{run_id}:{case['id']}", output):
                pass
            answer = output.get("content", "")
            if not answer and output.get("final_messages"):
                answer = content_text(output["final_messages"][-1]["data"]["content"])
        except Exception as exc:
            answer, error = "", str(exc)
        tool_names = {call["name"] for call in output.get("tool_calls", [])}
        chunk_ids = {r["chunk_id"] for r in refs}
        checks = {
            "answer_contains": not case["expected_answer"]
            or case["expected_answer"].strip().lower() in answer.lower(),
            "tools_recall": set(case["expected_tools"]) <= tool_names,
            "chunks_recall": set(case["expected_chunk_ids"]) <= chunk_ids,
        }
        success = not error and bool(answer) and all(checks.values())
        passed += int(success)
        await rt.db.add(
            t.eval_results,
            {
                "run_id": run_id,
                "case_id": case["id"],
                "actual_answer": answer,
                "tool_trace": output.get("tool_calls", []),
                "scores": checks,
                "passed": success,
                "latency_ms": int((time.monotonic() - start) * 1000),
                "tokens": output.get("prompt_tokens", 0) + output.get("completion_tokens", 0),
                "error": error,
            },
        )
    await rt.db.change(
        t.eval_runs,
        run_id,
        {
            "status": "succeeded",
            "total": len(cases),
            "passed": passed,
            "metrics": {
                "pass_rate": passed / len(cases) if cases else 0,
                "method": "answer_contains+tool_recall+chunk_recall",
            },
        },
    )
