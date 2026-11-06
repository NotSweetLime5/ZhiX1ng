# Project7 真实模型评测

`agentic_rag_v1` 是手工构造的合成开发评测集：12份虚构星澜云文档、30道固定题。文档与标准答案不含用户业务数据，不描述现实服务。类别为直接查询6题、跨文档推理8题、计算6题、时间与版本4题、信息不足3题、提示注入与规则绕过3题。

2026年11月5日已完成三轮正式实验：[结果及复核](../../EVALUATION.md)。普通RAG为80/90，AgenticRAG为87/90，同时记录Token增加和P95耗时变化。

## 冻结的实验协议

- 普通RAG：原问题经过生产 `RAG.retrieve` 检索一次，取4个片段，再进行一次回答模型调用。
- AgenticRAG：相同的初始检索与共同系统规则；额外提供 `knowledge_search`，最多补查3次，每次4个片段，最多5轮模型调用。工具只可访问本次合成知识库。查询由模型选择，没有传入标准答案或预先指定的补查词。
- 两组复用生产的Milvus dense+BM25/RRF检索、ETL、模型网关和 `AgentRuntime.react`，没有检索或模型替身。这是显式构建的评测配置，不代表每个管理页面现有智能体都自动启用了补查工具。
- 同一回答模型、temperature=0、top_p=1、请求输出上限900；无备用模型。默认每题每组重复3次，共180个回答样本，实际模型调用数可能更多，因为Agentic需要多轮调用。随机种子20261105，随机化题目与两组执行先后顺序，并发2。
- 每个已保存回答再由同一模型自动评审一次，temperature=0，请求输出上限500。评审看不到方案名称，只看到题目、参考答案、完整合成资料和回答者实际收到的证据。
- 主通过标准在运行前固定：评审判定正确且有依据，引用均来自实际检索结果；可回答题必须有来源引用。拒答题可以不引用，但不能伪造引用。遗漏的关键结论、错误数字或额外错误事实也应失败。评审JSON类型严格校验，基础设施失败和评审失败不计通过，分母不因失败缩小。
- 标准答案与完整题集仅在评审阶段使用；回答模型只见本题问题和实际检索片段。实验不预设Agentic一定提升。

## 实际运行

先在仓库根目录恢复本机已有基础服务，不删除数据卷：

```powershell
docker compose up -d --wait postgres redis minio etcd milvus
cd backend
uv sync --frozen
uv run python -m app.evaluation.benchmark --repeats 3 --concurrency 2
```

模型和Embedding使用本机 `.env` 连接的数据库中的现有配置，不把密钥放入命令行或结果文件。**这个命令会调用真实模型，可能产生供应商费用**；pytest中的评分边界测试不会调用模型。可用 `--model-id` 显式固定回答与评审模型。

小样本验证会写入独立目录，不覆盖全量实验：

```powershell
uv run python -m app.evaluation.benchmark --repeats 1 --cases q01,q07,q16,q19,q24,q26
```

每次启动打印独立输出目录。恢复时需使用原来的全部参数，并加 `--resume eval/runs/<run>`；数据、执行代码、参数或模型变化时拒绝续跑。已保存的回答和评审不会重新调用模型，已保存的失败结果也保留。恢复未完成的回答时可能重新索引合成资料，Embedding调用会另行记录。

离线重建统计与报告，无需数据库或模型服务：

```powershell
uv run python -m app.evaluation.benchmark --analyze eval/runs/<run>
uv run pytest -q tests/test_benchmark_scoring.py
```

## 留存与口径

每轮留存 `manifest.json`（模型、参数、提示词、源码/资料SHA-256、版本）、`source_snapshot/`、`dataset_snapshot.json`、`indexed_chunks.json`、随机执行顺序、逐回答JSONL、逐评审JSONL、合并结果、统计和报告。回答含实际证据和补查轨迹，不记录模型内部推理。只使用临时禁用登录账户和独立向量集合，结束后清理其对象、集合和数据库记录；清理前后校验原有文档、片段与内容指纹。

耗时以墙钟计算，包含检索、查询Embedding和回答生成，排除索引与自动评审；P50/P95使用nearest-rank。`first_answer_token_ms` 是首个可见文本块，可能是工具前说明，不能当作最终答案开始时间。Token按SDK返回的用量统计，包含供应商计入的推理Token；缺失值标记为空，不伪装成0。回答与评审用量分开统计，Embedding调用单独记录，但SDK未暴露其Token用量。计数为逻辑调用，不包含不可见的SDK内部HTTP重试。

这是合成开发集，且小样本验证用于修复执行器，并非独立保留测试集。相同模型自动评审有偏差，不能宣称人工验证的真实业务准确率；三次重复也不代表独立用户样本或统计显著性。两组计算预算不同，应同时报告通过数、Token和耗时。复核意见另存，不能事后改题、改评分口径或覆盖原始通过数。
