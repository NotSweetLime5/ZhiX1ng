"""Probe and import a local model configuration and document folder."""

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage
from langchain_openai import OpenAIEmbeddings

from app import models as t
from app.cli import configure_loop
from app.core.config import settings
from app.runtime import Runtime
from app.services.llm import Descriptor, Gateway
from app.services.local_config import read_config, redact_error
from app.services.local_import import configure_models, import_document, save_default_aliases, setup_knowledge


def report(event, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


async def probe(specs):
    gateway = Gateway(None, None, settings())
    results = {}
    for spec in specs:
        try:
            if spec.kind == "chat":
                descriptor = Descriptor(
                    {"model_name": spec.model_name, "max_output": 512},
                    {"base_url": spec.base_url},
                    spec.api_key,
                )
                answer = ""
                model = gateway.chat(descriptor, {"temperature": 0.1, "top_p": 0.9, "max_tokens": 512})
                async with asyncio.timeout(90):
                    async for chunk in model.astream([HumanMessage(content="请只回复四个字：连接成功")]):
                        if isinstance(chunk.content, str):
                            answer += chunk.content
                if not answer.strip():
                    raise ValueError("模型未返回正文")
                report(
                    "probe",
                    provider=spec.provider_name,
                    model=spec.model_name,
                    status="ok",
                    answer=answer[:80],
                )
            else:
                embedder = OpenAIEmbeddings(
                    model=spec.model_name,
                    base_url=spec.base_url,
                    api_key=spec.api_key,
                    check_embedding_ctx_length=False,
                    max_retries=0,
                    request_timeout=60,
                )
                vectors = await embedder.aembed_documents(
                    ["RAG 将外部知识检索后交给模型回答。", "Agent 使用工具完成任务。"]
                )
                dim = len(vectors[0])
                if spec.dimensions and dim != spec.dimensions:
                    raise ValueError(f"Embedding 实际维度 {dim} 与配置 {spec.dimensions} 不一致")
                report(
                    "probe",
                    provider=spec.provider_name,
                    model=spec.model_name,
                    status="ok",
                    dimensions=dim,
                    count=len(vectors),
                )
            results[spec.code] = True
        except Exception as exc:
            results[spec.code] = False
            report(
                "probe",
                provider=spec.provider_name,
                model=spec.model_name,
                status="failed",
                error=redact_error(exc, specs),
            )
    return results


async def run(args):
    specs = read_config(args.config)
    if not args.skip_probe:
        results = await probe(specs)
        if not all(results.values()):
            raise SystemExit("模型连通性检查未全部通过；尚未导入配置或文档。")
    if args.check_only:
        return
    if not args.documents or not args.documents.is_dir():
        raise SystemExit("需要 --documents 指定存在的文档目录")
    files = sorted(
        p
        for p in args.documents.iterdir()
        if p.is_file() and p.suffix.lower() in {".pdf", ".docx", ".txt", ".md", ".html"}
    )
    if not files:
        raise SystemExit("目录中没有支持的文档")
    cfg = settings().model_copy(
        update={
            "default_chat": specs[0].model_name,
            "default_embedding": next(s.model_name for s in specs if s.kind == "embedding"),
        }
    )
    rt = await Runtime(cfg).start()
    try:
        users = await rt.db.rows(
            t.users,
            t.users.c.username == args.username,
            t.users.c.role == "admin",
            t.users.c.status == 1,
            limit=1,
        )
        if not users:
            raise ValueError("导入用户需要是已存在的启用管理员")
        user = users[0]
        configured = await configure_models(rt, specs)
        save_default_aliases(specs)
        kb, agent = await setup_knowledge(rt, user, configured)
        report("configured", models=configured, kb_id=kb["id"], agent_id=agent["id"], file_count=len(files))
        if args.configure_only:
            return
        doc_ids = []
        for path in files:
            doc, created = await import_document(rt, user, kb, path)
            doc_ids.append(doc["id"])
            report("document", filename=path.name, id=doc["id"], uploaded=created, status=doc["status"])
        docs = await wait_for_documents(rt, doc_ids, specs, args.timeout)
        queries = [
            "Agent Skills 的组成是什么，与 MCP 有什么关系？",
            "RAG 与 Fine-tuning 的区别是什么？",
            "如何减少大模型的幻觉？",
        ]
        retrieval = []
        for query in queries:
            refs = await rt.rag.retrieve(user["id"], kb["id"], query)
            if not refs:
                raise ValueError("检索测试未命中资料")
            result = {
                "query": query,
                "sources": [
                    {"filename": r["filename"], "page": r["page"], "chunk_id": r["chunk_id"]} for r in refs
                ],
            }
            retrieval.append(result)
            report("retrieval", **result)
        answers = []
        tokens = await rt.security.tokens(user)
        for code, query in zip(("deepseek", "qwen"), queries[:2], strict=True):
            answer = await verify_chat(tokens["access_token"], agent["id"], configured[code], query)
            answers.append({"provider": code, **answer})
            report(
                "answer",
                provider=code,
                session_id=answer["session_id"],
                refs=len(answer["refs"]),
                text=answer["answer"][:300],
            )
        result = {
            "models": [
                {
                    "provider": s.provider_name,
                    "name": s.model_name,
                    "type": s.kind,
                    "dimensions": s.dimensions,
                    "id": configured[s.code],
                }
                for s in specs
            ],
            "knowledge_base": {"id": kb["id"], "name": kb["name"]},
            "agent": {"id": agent["id"], "name": agent["name"]},
            "documents": [
                {"id": d["id"], "filename": d["filename"], "status": d["status"], "chunks": d["chunk_count"]}
                for d in docs
            ],
            "total_chunks": sum(d["chunk_count"] for d in docs),
            "retrieval": retrieval,
            "answers": answers,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        report("complete", documents=len(docs), chunks=result["total_chunks"], report=str(args.report))
    except Exception as exc:
        raise SystemExit(redact_error(exc, specs)) from None
    finally:
        await rt.close()


async def wait_for_documents(rt, doc_ids, specs, wait_seconds):
    deadline = time.monotonic() + wait_seconds
    previous = None
    while time.monotonic() < deadline:
        docs = await rt.db.rows(t.documents, t.documents.c.id.in_(doc_ids), limit=10000)
        counts = {status: sum(d["status"] == status for d in docs) for status in {d["status"] for d in docs}}
        if counts != previous:
            report("indexing", statuses=counts)
            previous = counts
        if len(docs) == len(doc_ids) and all(d["status"] == "ready" for d in docs):
            return docs
        failed_jobs = await rt.db.rows(
            t.jobs,
            t.jobs.c.kind == "doc_etl",
            t.jobs.c.status == "failed",
            t.jobs.c.payload["doc_id"].as_integer().in_(doc_ids),
            limit=10000,
        )
        if failed_jobs:
            errors = [redact_error(ValueError(job["error"]), specs) for job in failed_jobs]
            raise ValueError(f"文档任务失败：{errors}")
        await asyncio.sleep(2)
    raise TimeoutError("索引等待超时；已上传的文档会继续由 Worker 处理，请检查文档状态")


async def verify_chat(token, agent_id, model_id, query):
    result = {"session_id": None, "refs": [], "answer": ""}
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST",
            "http://127.0.0.1:8080/api/v1/chat/stream",
            headers={"Authorization": "Bearer " + token},
            json={
                "agent_id": agent_id,
                "model_config_id": model_id,
                "content": query + " 请用150字以内回答并标注资料编号。",
            },
        ) as response:
            response.raise_for_status()
            event = ""
            completed = False
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    if event == "meta":
                        result["session_id"] = data["session_id"]
                    elif event == "refs":
                        result["refs"] = [
                            {k: r[k] for k in ("filename", "page", "chunk_id")} for r in data["items"]
                        ]
                    elif event == "delta":
                        result["answer"] += data["content"]
                    elif event == "error":
                        raise ValueError(data["message"])
                    elif event == "done":
                        completed = True
            if not completed or not result["answer"].strip() or not result["refs"]:
                raise ValueError("RAG 对话未正常完成，或未返回来源/正文")
    return result


def main():
    configure_loop()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--documents", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--configure-only", action="store_true")
    parser.add_argument("--skip-probe", action="store_true", help="已有连通性验证时避免重复调用")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--report", type=Path, default=Path("data/local-import-result.json"))
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
