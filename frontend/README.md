# Zhixing Web 控制台

React 18 + TypeScript + TailwindCSS + GSAP 前端，与 `../backend/app`（FastAPI）通过 REST + SSE 通信。

## 快速开始

```bash
npm install
npm run dev        # http://localhost:5173，/api 已代理到 http://localhost:8080
npm run build      # 类型检查 + 生产构建（dist/）
npm run typecheck  # 仅类型检查
npm test           # 流协议、会话隔离、上传/来源与 Agent 配置回归测试
```

Windows 可在项目目录使用 `start.ps1 setup`、`start.ps1 api`、`start.ps1 worker`；知识库处理需要 Worker 运行。
后端地址可用环境变量覆盖：`NX_BACKEND_URL=http://other:8080 npm run dev`。

## 功能地图

| 路由 | 说明 |
|---|---|
| `/chat` | 流式对话、停止后同步、显式重试、会话切换隔离、工具状态、按需滚动及可点击的来源 |
| `/agents` | 按名称选择模型和知识库、主备模型、参数校验、工具绑定、保存后试聊 |
| `/memories` | 长期记忆：列表/归档/删除/手动抽取 |
| `/kbs` `/kbs/:id` | 多文件上传队列与字节进度、处理状态自动更新、失败重试、分页分块、原文查看与检索核查 |
| `/workflows` `/workflows/runs` | 工作流：YAML DSL 编辑 + 校验 + 同步执行；执行记录 + HITL 审批 |
| `/admin/models` | 供应商 / 模型配置（admin） |
| `/admin/integrations` | MCP Server（同步/健康检查/工具调试）、A2A 远程 Agent（注册/委派）（admin） |
| `/admin/evaluations` | 评估集、用例、后台执行和结果查看（admin） |

## 架构

```
src/
├── api/        # FastAPI 接口封装（类型化）
├── types/      # 与后端契约一致的领域类型
├── lib/        # request（401 静默刷新单飞）/ sse（POST SSE 解析器）/ gsap 动效 / format
├── stores/     # zustand：auth（双 Token）/ chat（SSE 状态机）/ ui（Toast）
├── components/ # layout（侧边栏/顶栏）+ ui 原语（Modal/Toast/Confirm…）
└── pages/      # 路由页面（router.tsx 含登录/admin 守卫）
```

关键设计（契约驱动，字段均可在后端找到出处）：

- **SSE 解析**：`lib/sse.ts` 用 fetch + ReadableStream 手动解析 `event:\ndata:` 帧（EventSource 不支持 POST），半帧缓冲、中断静默、异常兜底。
- **状态机**：`stores/chat.ts` 以 `reduce` 归约 12 种事件；流结束以服务端消息列表为唯一事实源重拉。
- **认证**：access 在内存、refresh 在 localStorage；401 单飞刷新并重放；启动 bootstrap 恢复会话。
- **设计系统**：背景 `#14171c`、主文字 `#e9ecef`、参数小字 `#94a3b8`、选中态 `#2563eb`、输入框 `#1e2229`，统一 SVG 图标、卡片、表单与 Markdown 排版；GSAP 提供页面和消息动效。
- **聊天布局**：顶部选择智能体，灵感卡片填入输入框；窄屏导航折叠为图标，会话通过抽屉查看。

三项体验改进的文件入口、接口及验证说明见 [前端体验改进](EXPERIENCE.md)。
