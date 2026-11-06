Zhixing · AI Agent 与知识库平台
一个可自托管的 AI Agent 工作台，覆盖智能体编排、RAG 知识库、工作流、长期记忆、评估与工具集成，前后端一体。本项目是原 Go 版 Agent 平台的 Python 重写，品牌与应用元信息统一为 Zhixing（后端 v2.0.0）。
核心能力
- 对话与 Agent：SSE 流式对话、工具/委派/引用事件的时间线、会话隔离与显式重试；智能体可配置主备模型、参数与知识库绑定。
- 知识库：多文件上传队列、文档解析与 PDF 中英文 OCR、分块、向量 + BM25 检索、原文与引用段落回看；后台 Worker 处理 ETL 任务。
- 工作流与记忆：YAML DSL 工作流编排、执行记录与 HITL 审批；长期记忆的抽取、归档与手动管理。
- 集成与评估：MCP Server（8086，只读工具）、A2A 远程 Agent（8082）、管理端评估集与结果查看。
- 工程能力：Docker 代码沙箱、Redis Streams 任务队列（租约/重试/死信）、OpenTelemetry + Prometheus + Grafana 可观测性，以及前后端回归测试。
