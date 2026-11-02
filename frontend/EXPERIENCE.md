# Zhixing：聊天、知识库与 Agent 配置体验

更新：2026-11-02。范围为三条现有业务流程，不新增工作流画布或其他产品模块。

## 1. 聊天

- 每次发送绑定独立的视图代次；切换会话时取消旧流，迟到的事件和历史响应不能覆盖新会话。
- 停止后保留临时内容，最多短暂轮询约 3 秒等待服务端 assistant 收尾；没有同步成功则提示刷新，不自动重复执行模型或工具。
- 错误提供显式重新发送；历史中断/失败回答也能重新发送原问题。它创建新一轮，不是继续原检查点，工具可能再次执行。
- 工具按事件 ID 配对，并显示运行、失败或停止等待结果；委派事件更新专家名称。
- 用户上翻阅读时暂停自动跟随，使用“回到最新消息”恢复；长回答不会持续把用户拖回底部。
- SSE 支持分包、CRLF、多行 data 和中文流式解码；只在 401 握手被拒时续期重发，已开始的回答不会自动重试。

VSCode 入口：`frontend/src/stores/chat.ts`、`frontend/src/lib/sse.ts`、`frontend/src/pages/chat/ChatPage.tsx`、`Composer.tsx`、`MessageBubble.tsx`。

## 2. 知识库

- 支持多选或拖入文件，顺序上传；单文件失败不阻止后续文件。每次最多 20 个，每个 1 字节～20 MB。
- 进度来自浏览器实际发送字节。100% 后仍要等待服务端确认；上传完成和文档可检索是不同状态。
- 处理中的文档递归轮询，不重叠请求；显示等待、解析/OCR、切块、向量化、可检索阶段。没有处理中任务时停止自动轮询。
- 展开错误原因，失败文档可重试；后端校验所有权、锁住文档行并检查活跃任务，避免连续点击重复登记任务。
- 分块分页显示。聊天来源、检索结果及文档名称可打开来源面板；引用段落和页码按当前有效记录读取。
- 原文件通过 Bearer 鉴权后获取 Blob，Token 不放进 iframe URL。PDF 使用浏览器阅读器及 `#page=`；若浏览器不支持内嵌 PDF，可下载核对。文本以纯文本预览，DOCX 提供下载，不执行 HTML 原文。

新增后端接口（均需登录且仅允许访问自己的有效资料）：

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/documents/{id}` | 文档元信息 |
| `GET /api/v1/documents/{id}/content` | 读取原文件 |
| `GET /api/v1/chunks/{id}/source` | 引用段落、文档和页码 |
| `POST /api/v1/documents/{id}/retry` | 重新登记失败文档的处理任务 |

VSCode 入口：`frontend/src/components/knowledge/UploadQueue.tsx`、`SourceViewer.tsx`、`frontend/src/pages/kbs/KBDetailPage.tsx`、`backend/app/services/knowledge.py`、`backend/app/api/routes/knowledge.py`。

## 3. Agent 配置

- 使用模型名称和供应商下拉选择主备模型；使用知识库名称多选，不需要手填 ID。普通用户只调用已有用户级模型/知识库接口，不需要管理员权限。
- 校验名称、温度、输出上限、迭代次数、消息窗口以及重复备用模型；不合法时保留草稿并显示字段错误。
- 选项加载失败时允许重新加载并阻止保存；失效绑定不会静默丢弃，用户需明确移除或重新选择。
- 编辑时保留原工具绑定 config 和其他 Agent.config 字段；清除备用模型使用显式 null。
- “保存并试聊”先保存成功，再跳到 `/chat?agent=<id>`；聊天页建立新对话并选中该 Agent，不自动调用付费模型。

VSCode 入口：`frontend/src/pages/agents/AgentsPage.tsx`、`frontend/src/lib/agent-form.ts`、`frontend/src/pages/chat/ChatPage.tsx`。

## 4. 验证

```powershell
Set-Location -LiteralPath F:\project7\nexus-agent\frontend
npm test
npm run build

Set-Location -LiteralPath F:\project7\nexus-agent\backend
uv run ruff check app alembic tests
uv run pytest -q tests/test_document_experience.py tests/test_backend.py::test_react_sse_and_history tests/test_reliability.py::test_disconnected_stream_persists_interrupted_message
```

后端测试使用隔离数据库、对象桶和索引命名空间，模型为测试替身；需 PostgreSQL、Redis、MinIO、Milvus 可用。测试覆盖原文/引用权限、HTML 惰性呈现、删除后的不可访问、重试去重，以及已有聊天/中断落库回归。前端测试覆盖协议、竞态、停止与重试、上传失败后继续、来源 Blob 清理、状态轮询与表单保存试聊。

此轮没有进行付费模型调用或性能压测。来源授权在后端验证，页面隐藏和前端校验不能替代它。
