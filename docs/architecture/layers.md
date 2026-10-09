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

## 阶段七：意图、上下文与记忆（已实现）

实施进度与结果见[对话式练习开发计划](../plans/CONVERSATION_PRACTICE_PLAN.md)。复用现有 SQLite、LangGraph、LangChain 适配器及任务队列，不引入新记忆框架或服务。

| 层 | 新职责 | 边界 |
|---|---|---|
| controller | 自然语言输入、消息流、练习状态、简历快照及偏好 DTO | 只提交异步任务，不等待模型、不判断业务意图 |
| service | 冻结输入、上下文选择、意图校验、动作编排、撤销偏好和删除协调 | 校验归属与版本；已保存回答和反馈绑定同一回答版本 |
| domain | 练习意图、目标规则、题组导航、偏好作用范围和记忆优先级 | 不依赖 LLM、HTTP 或数据库；模型输出须通过领域校验 |
| repository | 消息顺序、短期状态、摘要边界、事实快照、偏好来源及完成步骤 | 持久化支持刷新恢复、重试去重和来源级联清理 |
| infrastructure | intentNode、LLM 结构化输出、队列消费及统计 | 仅执行受校验动作；短图不等待人工输入 |

上下文组装由 service 读取仓储，分开提供事实、练习状态、偏好和非事实历史摘要。完整历史存数据库，发送内容按预算裁剪；当前输入和关键目标优先，联系人信息和疑似密钥发送前脱敏。模型识别采用受校验的结构化输出，不用固定关键词规则代替意图节点。

提交事务记录消息及不可变输入快照，任务执行保留步骤完成标识。回答落库和该步骤标识必须在同一事务完成，反馈失败不重复插入回答；偏好同样按来源和消息身份去重。取消/删除和结果发布之间必须执行最终状态检查，避免已删除数据被运行中的任务重建。

LangGraph 只编排一次输入的识别和明确动作，不作为事实数据库。澄清事项入库后结束运行；下一条输入创建新短图。具体回答和评价只属于当前对话，长期偏好只保存候选人明确要求且可撤销的内容。

前端继续 `pages -> features -> api/types`：页面提供单历史侧栏、消息区、统一输入框与顶部简历入口；feature 管理草稿、当前题、轮询、取消/重试、偏好撤销和简历面板；HTTP 和类型集中维护。简历面板只读已确认历史快照，通用组件不直接获取业务数据。

持久化新增 `conversation_practice_states`、`practice_events`、`practice_inputs`、`practice_preferences` 和 `practice_preference_sources`。消息序号与请求 ID 由数据库唯一约束保护；对话锁通过条件 UPDATE 获取，发布前检查运行状态并取得写锁。模型等待期间不持有数据库写锁。数据库依然是事实来源，当前本地队列沿用线程 Worker，部署可沿用 Celery。

新模块入口为 `domain/practice_intent.py`、`repository/practice_repository.py`、`service/practice_service.py` 和 `dto/practice.py`。已明确快捷动作复用原 Agent 服务，Worker 发布结果时写入消息流，不重复识别意图。

## 阶段八：历史管理架构（已实现）

实现见[历史管理开发计划](../plans/CONVERSATION_HISTORY_PLAN.md)。复用数据库与现有任务锁，不新增框架或服务；后端管理接口已按分层边界落地，前端两个入口共用历史 feature。

- domain：分组/标题校验、归档写入许可、幂等管理状态和排序不变量。
- repository：集合所有版本下的历史查询、管理字段、分组唯一约束和对话级清理；本功能涉及的 SQL 从 service 归入仓储。
- service：管理事务、任务忙碌协调、删除与偏好来源清理；所有练习及兼容写入口共用归档许可。
- controller/DTO：增量管理字段、分组 REST 资源和稳定错误 code，不进行业务状态判断。
- 前端：两个页面组合共同的历史 feature，查询/变更经 `api/conversations.ts`，复用查询键和缓存刷新。App 中独立历史入口改为 feature 组合，不直接请求业务数据。

新增分组表和对话 `group_id`、`pinned_at`、`archived_at`、`last_activity_at`；外键删除组时设置为空，集合删除级联清组。材料版本关系继续是对话归属与事实边界来源，不另存可冲突的材料集合关联。

任务提交与归档/单独删除在同一数据库事务内协调，避免检查和修改间的竞争；终止状态或已删除任务继续阻止 Worker 发布。元数据更新时间和练习活动时间分离，管理操作不会影响消息顺序、上下文或已提交任务输入。
