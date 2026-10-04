# 分层架构

## 后端

```text
controller -> service -> domain
                   -> repository -> infrastructure
```

- `controller` 只处理 HTTP、DTO、状态码和 Problem Details。
- `service` 编排一个完整用例，负责事务边界和跨仓储协调。
- `domain` 保存材料版本、证据、对话和补充内容的不变量。
- `repository` 暴露持久化所需的最小接口，业务层不拼 SQL。
- `infrastructure` 适配 SQLAlchemy、文件系统、文档解析、OCR 和 LLM。

Agent 追问阶段增加以下分层边界：

```text
controller -> run_service -> domain/practice
                         -> repository -> infrastructure
                         -> task_queue -> langgraph_worker
                                              |-> llm_adapter
                                              |-> code_search_adapter
```

- `run_service` 只负责创建幂等的 `llmRun`、校验对话/材料版本绑定和返回任务状态，不在 HTTP 请求中等待模型完成。
- `domain/practice` 保存问题范围、问题版本、练习轮次、参考答案版本和证据等级等不变量。
- `task_queue` 提供统一队列适配层：本地默认使用线程 worker 便于 MVP 零依赖启动，生产通过 `TASK_QUEUE_BACKEND=celery` 切换到 Celery + Redis；任务失败、取消和重试状态持久化到数据库。Redis 7 + Celery worker 已完成真实消费验收。
- `langgraph_worker` 每次只运行一个用户动作对应的短图，不在图内等待候选人输入。
- `llm_adapter` 使用 `langchain-openai` 访问 OpenAI-compatible 模型，Pydantic 校验节点输出。
- `code_search_adapter` 只允许隔离目录中的白名单文件读取、`rg/grep` 和 Tree-sitter 静态解析，禁止任意 shell、执行、构建和测试。
- 业务数据库是对话、任务和证据快照的唯一事实来源；LangGraph 不另建一套长期事实状态。

当前实现由显式 Worker 节点承载问题、反馈、参考答案和追问短任务，并通过 `run_short_graph` 运行带有业务节点名称的 LangGraph 短图；每个用户动作只执行一次，不在图内等待输入。所有模型调用经 `LLMClient -> LangChainOpenAIAdapter -> ChatOpenAI`，应用层不直接发起 HTTP 请求。Celery 入口为 `backend/app/agent_worker.py`，本地线程队列和 Celery 的 HTTP 契约一致。

文档/LLM 的旧 `app/services/` 模块目前由 `app/infrastructure/ingestion.py` 和 `app/infrastructure/llm.py` 作为兼容适配入口导出；业务用例只从 `infrastructure` 入口依赖，后续可在不改动 service 层的情况下替换具体实现。

## 前端

```text
pages -> features -> api
                  -> types
components <- features
```

页面只组合业务模块；业务模块管理查询、变更和交互；HTTP 细节集中在 `api/`；通用组件不依赖材料集合或对话业务。

Agent 追问前端继续遵守 `pages -> features -> api/types`：`features/practice` 管理问题范围、练习轮次和任务轮询；参考答案、代码证据和通用知识使用分区展示；页面不直接调用 Worker 或 LLM。

## 事务和版本

上传创建新的不可变材料版本。对话创建时记录 `revisionId`，后续替换或删除材料不影响旧对话。单份材料删除由 service 创建排除目标材料的新当前版本；删除材料集合使用一个服务用例级联清理数据库和本地文件。

问题版本绑定创建时的材料版本、问题范围和提示版本；回答通过 `practice_answers` 保存不可变版本；反馈绑定回答版本；参考答案绑定问题版本和代码证据快照。`llmRun` 只记录异步任务生命周期和结构化结果，不保存隐藏推理过程；删除材料集合时级联删除练习轮次、回答、反馈、问题版本、参考答案、代码证据快照和任务记录。
