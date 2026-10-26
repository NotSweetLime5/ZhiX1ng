# Zhixing Python 后端

FastAPI + Pydantic + SQLAlchemy + LangChain + LangGraph。PostgreSQL 保存业务数据、任务和检查点，Milvus 提供向量与 BM25 检索。

## 目录与职责

```text
app/
├── api/
│   ├── routes/          # 按领域拆分的 HTTP、SSE 和 A2A 接口
│   ├── dependencies.py # 认证、管理员权限、分页和 Runtime 注入
│   └── responses.py    # 统一响应包络
├── models/             # 按领域拆分的 SQLAlchemy Core 表与统一 metadata
├── schemas/            # Pydantic 请求校验、模型配置与 Agent 计划结构
├── services/           # 业务规则、资源归属、事务、模型网关、RAG 和评估
├── repositories/       # PostgreSQL 异步数据访问、分页和资源锁
├── agents/             # LangChain ReAct、LangGraph Host/规划执行与工作流
├── infrastructure/     # Milvus、MinIO、文档解析、PDF 中文/英文 OCR
├── core/               # 配置、认证加密、业务异常和序列化
├── scripts/           # 初始数据、本机模型配置与文档导入
├── runtime.py          # 依赖装配和连接生命周期
├── main.py             # FastAPI 入口、异常映射和可观测性
├── worker.py           # 后台任务入口、租约、心跳和重试
└── cli.py              # 跨平台启动与终端对话
alembic/                # 数据库迁移
tests/                  # 集成与分层回归测试
deployments/            # 可选沙箱、SearXNG 配置
```

调用路径为 `routes → services → repositories / models / infrastructure`。路由不执行 SQL 或数据库写入，服务不导入 FastAPI 或接口模块；业务异常由 `main.py` 转成原有 HTTP 状态码和响应格式。服务层负责事务边界，跨资源操作通过同一数据库连接完成。

`models` 使用 SQLAlchemy Core 的 `Table`，并非 ORM 实体类。保留现有数据库表结构与显式 SQL 查询，避免目录整理引入数据迁移。`schemas` 是 Pydantic 输入模型，管理接口同样支持局部更新：未提供的字段不写入数据库，供应商 API Key 留空保持原值。

## 运行与验证

在项目根目录使用 `start.ps1 setup/api/worker/web/test`。也可以在 backend 内执行：

```bash
uv sync --frozen
uv run python -m app.cli migrate
uv run python -m app.cli seed
uv run python -m app.cli serve
uv run python -m app.cli worker
uv run ruff check app alembic tests
uv run pytest -q
```

测试依赖真实 PostgreSQL、Redis、MinIO、Milvus；模型调用使用测试替身，不会调用付费模型。配置和功能边界见 [迁移说明](../MIGRATION.md)。

本机模型与文档导入可使用 `uv run python -m app.scripts.import_local --help`。该工具先测试模型连通性，将凭据加密保存，再通过后台任务构建资料库，并验证带引用的真实问答。原始文档保持不变，重复运行按文件内容跳过已上传文档。

项目品牌与应用元信息统一为 **Zhixing**。现有工作目录、Compose 部署标识、数据库连接、对象存储桶和 `NX_` 配置前缀保持兼容，继续使用已配置的模型与知识库数据。
