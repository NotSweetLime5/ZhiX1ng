# Zhixing Python 后端

FastAPI + Pydantic + SQLAlchemy + LangChain + LangGraph。PostgreSQL 保存业务数据、任务提交记录和检查点；Redis Streams 负责异步投递、消费组、认领、重试与死信；Milvus 提供向量与 BM25 检索。

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
tests/                  # 集成、分层回归与旧版 API 兼容性测试
deployments/            # 可选沙箱、SearXNG 和可观测性配置
```

调用路径为 `routes → services → repositories / models / infrastructure`。路由不执行 SQL 或数据库写入，服务不导入 FastAPI 或接口模块；业务异常由 `main.py` 转成原有 HTTP 状态码和响应格式。服务层负责事务边界，跨资源操作通过同一数据库连接完成。

`models` 使用 SQLAlchemy Core 的 `Table`，并非 ORM 实体类。Python 版通过 Alembic 管理自己的表结构，不直接套用原版 Go 的迁移或表结构。`schemas` 是 Pydantic 输入模型，管理接口支持局部更新：未提供的字段不写入数据库，供应商 API Key 留空保持原值。

## 运行与验证

推荐在项目根目录使用 `start.ps1 setup`、`start.ps1 up` 和 `start.ps1 web`。开发时也可以在 backend 内分终端执行：

```bash
uv sync --frozen
uv run python -m app.cli createdb
uv run python -m app.cli migrate
uv run python -m app.cli seed
uv run python -m app.cli serve
uv run python -m app.cli worker
uv run python -m app.cli a2a
uv run python -m app.cli mcp
uv run python -m app.scripts.enable_integrations
uv run python -m app.cli chat --addr http://127.0.0.1:8080 --user your-username
uv run ruff check app alembic tests
uv run pytest -q
```

测试依赖真实 PostgreSQL、Redis、MinIO、Milvus；测试会创建临时 PostgreSQL 数据库、独立向量集合前缀和对象桶，结束后清理。模型调用使用测试替身与模拟 HTTP，不会调用付费模型。设置 `NX_TEST_SANDBOX=1` 可额外运行 Python、Shell、Go 的真实 Docker 沙箱测试。所有部署使用根目录的 `compose.yaml` 和本目录的 `Dockerfile`，后端配置使用 `.env` 中的 `NX_` 环境变量。数据库结构由 `alembic/` 和 `app/models/` 管理，初始数据由 `app/scripts/seed.py` 管理。

本机直接复用已有服务：PostgreSQL `127.0.0.1:5439/zhixing_python`，Milvus `http://127.0.0.1:19533` 中的 `zhixing_python` 数据库；`NX_MILVUS_DATABASE` 决定 Milvus 的逻辑数据库，`NX_MILVUS_NAMESPACE` 可进一步隔离同一数据库中的测试集合。`createdb` 只创建缺少的逻辑数据库，不重装服务或清空已有数据库。原 Go 数据库应保留，不能直接将它标记为 Python 迁移已完成。

首次创建管理员时，`NX_ADMIN_PASSWORD` 需要至少16字符，留空则生成一次性密码。`start.ps1 setup` 会为新安装生成密钥及管理员密码并写入本机 `.env`；已有账户密码不会被自动修改。生产模式设置 `NX_ENV=production`，要求 JWT 与加密密钥各至少32字符且互不相同。

终端对话通过 HTTP 登录 API，不再隐式使用本地管理员身份。`--addr` 可指定远程地址，`--user` 指定用户名，密码默认交互输入；自动化可使用 `NX_CLI_PASSWORD`。`/quit`、`quit`、`exit` 退出；同一终端继续同一个会话，显示工具、委派和引用事件。

代码执行返回 `exit_code/stdout/stderr/duration`，保留原 Python 的 `output` 合并字段。通过受审批工具链执行时，`sandbox_executions` 保存用户、代码 SHA-256、退出码、耗时和输出片段，不保存代码源文本字段。已有 Python 数据库通过迁移003补表。

模型兼容适配器继承 LangChain ChatOpenAI，并补充原版 OpenAI 兼容端点的 `reasoning_content` 读取与回传。相关 SDK 私有转换方法受固定版本和 HTTP/SSE 回归保护，升级 `langchain-openai` 时应运行完整回归。

旧 Go 后端的 `cmd/`、`internal/`、`configs/`、`migrations/`、`go.mod`、`go.sum` 及专用 Dockerfile、Compose 已移除。`tests/fixtures/legacy_api_routes.json` 保存删除前的 65 个 HTTP 入口，用于验证 FastAPI 的接口覆盖；集成测试验证认证、对话流、工具、记忆、知识库、工作流、MCP、A2A 和后台任务行为。

`start.ps1 up` 同时启动 SearXNG 与 Jaeger / Prometheus / Grafana，已有 API、模型、工具指标和 Grafana 面板。`NX_OTEL_ENDPOINT` 在宿主机运行时使用 `http://127.0.0.1:4318`，容器运行时使用 `http://jaeger:4318`；API、A2A 和 Worker 分别上报服务名。

Redis Streams 使用原版 `stream:doc-etl/g-docetl`、`stream:eval/g-eval` 和新增通用任务 `stream:jobs/g-jobs`。业务事务先提交任务记录，再由 Worker 发布，避免数据库提交与 Redis 投递之间丢任务；消费端保留 SQL 租约防止重复并发处理，失败重试耗尽后写入对应 `:dlq`。默认90秒接管无心跳任务。测试使用独立 Redis 命名空间。

MCP 在8086端口通过 Streamable HTTP 提供四个只读工具；A2A 独立8082端口兼容旧版 `type` 报文与匿名系统身份，同时支持现代 `kind` 报文。匿名身份单独存储会话，不能登录管理 API。切换宿主机开发模式时，运行 `enable_integrations` 将服务地址登记为127.0.0.1；Compose 模式通过 `start.ps1 up` 登记容器内地址。

可选代码沙箱使用 `docker build -f backend/deployments/sandbox.Dockerfile -t nexus-python-sandbox:local backend`（从项目根目录执行）构建，并通过 `NX_SANDBOX_ENABLED=true` 开启。沙箱保留 Python、Go、Shell 用户代码执行能力；其中的 Go 工具链仅服务于代码执行工具。

本机已经开启沙箱；Compose API 挂载 Docker socket 用于创建受限沙箱，MCP 不暴露代码执行、SQL 或用户文件工具。HTTP 白名单与沙箱开关来自 `.env`，不会因启动脚本覆盖已有供应商密钥。

真实服务验证使用 `docker compose exec -T api python -m app.scripts.verify_live --model-calls`。该选项允许少量真实模型请求；不加该选项只验证免费工具、沙箱和监控。临时 ETL 测试资料验证后会清理。本机证据保存在 `data/feature-live-check.json` 和 `data/model-live-check.json`，已去除凭据。

本机模型与文档导入可使用 `uv run python -m app.scripts.import_local --help`。该工具先测试模型连通性，将凭据加密保存，再通过后台任务构建资料库，并验证带引用的真实问答。原始文档保持不变，重复运行按文件内容跳过已上传文档。

项目品牌与应用元信息统一为 **Zhixing**。工作目录、Compose 部署标识和 `NX_` 配置前缀保留；本机配置已切换到独立的 Python 数据库与文档桶，已有模型配置、文档和索引经过复制与校验后继续使用，原库保留。

原版源码对照、修复项和验证边界见 [迁移核查报告](../MIGRATION_AUDIT.md)。
