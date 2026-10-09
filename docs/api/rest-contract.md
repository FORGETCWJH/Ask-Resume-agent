# RESTful API 契约

基础路径：`/api/v1`。JSON 字段使用 `camelCase`。

## 资源

| 方法 | 路径 | 成功状态 | 说明 |
|---|---|---:|---|
| GET | `/health` | 200 | 健康检查 |
| POST | `/material-sets` | 201 | 创建材料集合 |
| GET | `/material-sets` | 200 | 分页列出材料集合 |
| GET | `/material-sets/{id}` | 200 | 获取材料集合 |
| DELETE | `/material-sets/{id}` | 204 | 删除全部原始和派生数据 |
| POST | `/material-sets/{id}/materials` | 202 | 上传 `kind=resume\|projectArchive` 的材料 |
| GET | `/material-sets/{id}/materials` | 200 | 列出材料状态 |
| GET | `/material-sets/{id}/evidence` | 200 | 查询证据 |
| GET | `/material-sets/{id}/conversations` | 200 | 查询材料集合下的历史对话 |
| DELETE | `/materials/{materialId}` | 204 | 从当前版本移除单份材料，保留历史版本 |
| POST | `/materials/{materialId}/retry` | 200 | 重试项目档案静态解析 |
| GET | `/materials/{materialId}/recognition` | 200 | 获取简历结构化识别草稿和状态 |
| PATCH | `/materials/{materialId}/recognition` | 200 | 保存候选人编辑后的识别草稿 |
| POST | `/materials/{materialId}/recognition/retry` | 200 | 重试 OCR 或结构化识别 |
| POST | `/materials/{materialId}/recognition/confirm` | 200 | 按模块或全部确认识别结果 |
| POST | `/material-sets/{id}/conversations` | 201 | 创建绑定当前版本的对话 |
| GET | `/conversations/{id}` | 200 | 获取对话和消息 |
| POST | `/conversations/{id}/messages` | 201 | 发送一次直接 LLM 请求 |
| PATCH | `/conversations/{id}/supplements/{supplementId}` | 200 | 确认候选人补充内容 |

阶段一中，上传接口只触发本地文件解析/OCR和规则结构化处理，不调用远程 LLM。上传接口先返回 `202` 和材料状态，前端通过材料和识别接口轮询 `processing`、`partial`、`ready`、`failed`、`pending` 或 `awaitingConfirmation`。错误响应使用 `application/problem+json`：

```json
{
  "type": "https://example.com/problems/material-not-ready",
  "title": "Material is not ready",
  "status": 409,
  "detail": "材料仍在解析中",
  "code": "MATERIAL_NOT_READY",
  "traceId": "..."
}
```

## 后续阶段：发送消息

以下对话接口已保留用于后续阶段，阶段一不在前端开放，也不作为 OCR 提取验收范围。

```json
{
  "content": "这段经历我应该怎么解释？",
  "mode": "selectedPassageQuestion",
  "selection": {
    "materialId": "uuid",
    "text": "选中的文字",
    "startOffset": 10,
    "endOffset": 16
  }
}
```

`selection` 可以为 `null`。助手响应必须保留结构化 `questions`、`evidence`、`inferenceDrafts`、`evidenceGaps` 和 `feedback`；数组元素必须是对象。兼容层会将供应商返回的简单字符串元素归一化为 `{text: "..."}`，但无法推断的字段不会伪造额外事实。

## Agent 追问与异步 LLM 任务

Agent 追问使用独立的练习轮次和异步任务资源。旧的 `POST /conversations/{id}/messages` 保留为兼容接口；新的练习页面不得等待该接口同步完成模型调用。

| 方法 | 路径 | 成功状态 | 说明 |
|---|---|---:|---|
| POST | `/conversations/{conversationId}/question-runs` | 202 | 根据结构化问题范围创建问题生成任务 |
| GET | `/conversations/{conversationId}/practice-turns` | 200 | 获取练习轮次、问题版本、回答和结果状态 |
| POST | `/practice-turns/{turnId}/answers` | 201 | 保存一个候选人回答版本，不调用 LLM |
| POST | `/practice-turns/{turnId}/feedback-runs` | 202 | 创建回答反馈任务 |
| POST | `/practice-turns/{turnId}/reference-answer-runs` | 202 | 创建项目代码参考答案任务 |
| POST | `/practice-turns/{turnId}/follow-up-runs` | 202 | 创建下一条追问任务 |
| GET | `/llm-runs/{runId}` | 200 | 查询异步任务状态和结构化结果 |
| POST | `/llm-runs/{runId}/retry` | 202 | 保留旧任务并创建新的显式重试任务 |
| POST | `/llm-runs/{runId}/cancel` | 202 | 取消排队任务或尽力取消运行中任务 |

### 问题范围

```json
{
  "scopeType": "resumeSection|project|selectedEvidence|customTopic",
  "targetIds": ["uuid"],
  "topic": "缓存一致性和失败处理",
  "questionType": "implementation",
  "difficulty": "medium"
}
```

问题由模型生成，候选人不能直接编辑问题文本。相同范围默认复用当前问题；点击“换一个问题”才创建新问题版本。问题版本的指纹必须包含范围、材料版本、项目版本、提示版本和生成约束。

### 异步任务响应

创建问题、反馈、参考答案或追问任务时返回：

```json
{
  "runId": "uuid",
  "status": "queued",
  "runType": "question|feedback|referenceAnswer|followUp",
  "conversationId": "uuid",
  "practiceTurnId": "uuid"
}
```

任务状态为 `queued`、`running`、`succeeded`、`failed` 或 `cancelled`。网络错误和 5xx 由 Worker 有限重试；供应商返回的简单字符串字段会先归一化为结构化对象，无法归一化的结构化错误直接失败并需要候选人显式重试。

当前实现返回最小任务响应 `{runId, status}`，任务结果通过 `GET /llm-runs/{runId}` 查询。默认 `TASK_QUEUE_BACKEND=local` 使用进程内短任务 worker；部署 Redis 后设置 `TASK_QUEUE_BACKEND=celery`，由 `backend/app/agent_worker.py` 的 Celery worker 消费。每次显式重试创建新 `runId`，取消后的 Worker 不得写回成功。所有真实模型调用经 `LangChainOpenAIAdapter`，HTTP 请求不会等待模型结果。

### 练习轮次

`POST /practice-turns/{turnId}/answers` 请求体：

```json
{ "content": "候选人的回答文本" }
```

参考答案只在候选人提交回答并点击对应操作后生成，并绑定问题版本和代码证据快照。当前代码证据功能关闭时返回 `insufficient` 和限制说明；参考答案不可因用户修改回答而覆盖。

```json
{
  "answer": "基于当前项目代码可以确认的解释",
  "evidenceLevel": "direct|inferred|insufficient",
  "evidence": [
    {
      "path": "backend/app/service/example.py",
      "startLine": 20,
      "endLine": 42,
      "quote": "..."
    }
  ],
  "searchScope": ["backend/app/service"],
  "limitations": ["当前范围未找到事务边界的直接实现"],
  "genericExplanation": null
}
```

没有明确绑定项目档案时，不自动跨项目猜测。代码证据不足时返回限制和已搜索范围，不生成项目事实；通用知识必须单独触发并与项目参考答案分区展示。

### 幂等和权限

服务端根据 `conversationId + action + inputFingerprint` 复用已有 `queued`、`running` 或 `succeeded` 任务。`runId` 不是访问凭据，查询任务时必须校验候选人、对话、材料集合和材料版本绑定。重试创建新的 `llmRun`，不覆盖旧任务。

## 简历识别

`GET /materials/{materialId}/recognition` 返回：

```json
{
  "materialId": "uuid",
  "revisionId": "uuid",
  "materialStatus": "ready",
  "recognitionStatus": "awaitingConfirmation",
  "draft": {
    "personalInfo": {},
    "skills": {
      "content": "",
      "evidenceIds": [],
      "confidence": 0.0,
      "edited": false
    },
    "workExperiences": [],
    "projects": []
  },
  "warnings": [],
  "confirmedSections": [],
  "evidenceLinks": {}
}
```

`PATCH /materials/{materialId}/recognition` 请求体为 `{ "draft": { ... } }`，只更新结构化草稿，不修改原始文件或 OCR 文本。若修改已确认模块，该模块的事实证据会立即撤回并回到待确认状态，必须重新确认。

识别草稿采用紧凑结构：`skills` 是一个带 `content`、`evidenceIds` 和置信度元数据的完整文本对象；`workExperiences` 每条记录保留公司、职位、时间和一个完整 `description`；`projects` 每条记录保留名称、时间、角色、技术栈和一个完整 `description`。不再生成技能标签、工作经历嵌套项目、`background`、`responsibilities`、`contributions` 或独立 `metrics` 字段。原简历中已有的成果数字会合并进完整描述，不单独展示。

迁移版本 `0003_compact_resume_recognition` 会直接改写历史草稿 JSON 和证据字段路径；`0004_clean_compact_resume_content` 会清理项目内容误入技能段和历史重复描述。原始 OCR 文本与已确认事实证据不被静默覆盖。旧草稿中的指标内容会以“成果描述：”普通文本并入描述，用户重新编辑并确认后才生成当前格式的事实证据。

`POST /materials/{materialId}/recognition/retry` 请求体为 `{ "scope": "ocr|recognition|all", "pageNumber": 1 }`；`pageNumber` 可省略。阶段一的 `recognition` 使用本地规则重新生成草稿，不调用 LLM。PDF 可以按页重试 OCR；页不存在、OCR 失败和空页会通过 `warnings` 返回。DOCX 不支持页级重试，传入页码时会退化为整份解析并返回警告。

`POST /materials/{materialId}/recognition/confirm` 请求体为 `{ "section": "personalInfo|skills|workExperiences|projects|all" }`。只有确认后的模块会生成 `resume-recognition:<section>` 证据，未确认草稿不会出现在材料集合事实证据中。

`DELETE /materials/{materialId}` 只允许删除当前材料集合当前版本中的材料。服务创建排除该材料的新版本，旧版本、旧对话和历史证据保持可读；材料集合删除时才物理清理原始文件。材料不存在返回 `404 MATERIAL_NOT_FOUND`，材料不属于当前版本返回 `409 MATERIAL_NOT_ACTIVE`。

`POST /materials/{materialId}/retry` 只用于当前版本的 `project_archive` 材料；重试前清理该材料旧的证据索引，再重新读取 ZIP 白名单文本文件，不执行其中任何代码。简历材料应使用 `/recognition/retry`。

## 阶段七：对话式练习接口（已实现）

需求基准：[对话式练习](../requirements/conversation-practice.md)。下表接口已实现。已有 `/messages` 兼容接口和 `/practice-turns/{turnId}/answers` 保存行为不变。

| 方法 | 路径 | 成功状态 | 说明 |
|---|---|---:|---|
| POST | `/conversations/{id}/input-runs` | 202 | 保存自然语言输入并创建异步意图识别任务 |
| GET | `/conversations/{id}/practice-messages` | 200 | 按稳定顺序分页获取输入、问题、回答、结果和澄清消息 |
| GET | `/conversations/{id}/practice-state` | 200 | 获取当前主问题、问题组进度、追问链和待澄清状态 |
| GET | `/conversations/{id}/resume-snapshots` | 200 | 获取绑定版本的只读简历章节与原文依据 |
| POST | `/conversations/{id}/navigation-events` | 201 | 执行明确的下一题操作，不调用问题生成模型 |
| GET | `/practice-preferences` | 200 | 查询当前候选人的长期练习偏好 |
| PATCH | `/practice-preferences/{preferenceId}` | 200 | 显式修改长期练习偏好 |
| DELETE | `/practice-preferences/{preferenceId}` | 204 | 删除或撤销长期偏好，重复删除同样返回 204 |

### 自然语言输入与任务

```json
{
  "content": "我使用缓存降低查询压力，请点评我的回答",
  "clientRequestId": "uuid"
}
```

响应 `{ "runId": "uuid", "status": "queued", "messageId": "uuid" }`。提交立即返回，HTTP 不等待模型。每条输入都经意图节点；明确快捷按钮沿用对应动作接口。对话内一次只处理一个改变练习状态的输入，忙碌时返回 `409 CONVERSATION_BUSY`，前端保留草稿。

`clientRequestId` 在对话内唯一；同一 ID 和内容重复提交返回相同消息及任务，不重复创建回答或偏好。相同 ID 携带不同内容返回 `409 INPUT_IDEMPOTENCY_CONFLICT`。失败任务通过现有 `/llm-runs/{runId}/retry` 创建新运行记录，仍关联原消息并跳过已完成步骤。取消复用现有任务取消接口；已经保存的回答不会回滚，任务查询必须能明确展示已完成步骤。

`messageId` 是稳定提交身份（`practice_inputs.id`）；消息流中的输入事件通过 `inputId` 关联它。消息事件有独立 ID。运行中的快捷动作与输入共用对话任务锁。`practice-state` 返回 `activeRunId` 与最近的 `lastRunId`；重试更新最近任务指针，刷新后仍可恢复失败提示或当前任务。

`GET /llm-runs/{runId}` 沿用任务生命周期，新增 `runType=input` 和业务结果：

```json
{
  "outcome": "recognized",
  "action": "feedback",
  "practiceTurnId": "uuid",
  "answerVersionId": "uuid",
  "createdMessageIds": ["uuid"],
  "preferenceChanges": [],
  "clarification": null
}
```

`outcome` 为 `recognized|needsClarification|unsupported`。后两项均可为 `succeeded` 的正常业务结果，不当作供应商故障自动重试。真正模型/基础设施错误仍为 `failed`，保留稳定错误 code。

输入任务即使失败或取消，也返回已持久化的 `completedSteps`、`answerVersionId` 与 `preferenceChanges`，以区分回答已经保存和反馈尚未完成。普通 `generate` 在范围和提示版本不变时复用当前题组；明确 `regenerate` 才创建新组。输入仍进行意图识别，但复用题组不调用问题生成节点。

回答加点评指令先保存不可变回答版本，再生成绑定该版本的反馈；反馈失败时回答仍可查询。后端校验对话归属、目标问题、回答前置条件和冻结的版本，不直接执行未经校验的模型动作。当前无题且输入无法确定目标时先澄清，不把正文存为虚构问题的回答。

### 消息、题组与简历

`practice-messages` 接受 `afterSequence` 和有上限的 `limit`，返回 `{items, nextAfterSequence}`。消息包含 `id`、`sequence`、`role`、`messageType`、`content`、`runId`、`practiceTurnId`、`answerVersionId`、`createdAt`；不存在的关联为 `null`。消息类型区分输入、主问题、回答、反馈、参考答案、追问、澄清和状态提示，不将助手消息作为事实证据。

`navigation-events` 请求为 `{action: "nextQuestion", clientRequestId: "uuid"}`，返回当前题与问题组进度；组尾返回 `completed=true`，不生成新题。自然语言“下一题”经过意图节点后执行相同领域规则。

`resume-snapshots` 返回 `{conversationId, revisionId, resumes}`；每份包含文件名、材料 ID、确认章节、原文定位和 `snapshotStatus=available|missing`。未确认章节只显示状态，不返回草稿作为事实。旧对话无法恢复历史内容时返回 `missing` 及提示，不能回填最新简历。查看、轮询和刷新不调用 LLM。

### 偏好与快照边界

偏好对象包含 `id`、`key`、`value`、`revision`、`sourceConversationIds` 和时间。模型只能提出受支持键的变更；业务服务仅在候选人明确要求长期沿用时保存。修改请求为 `{value, expectedRevision}`；并发版本冲突返回 `409 PREFERENCE_VERSION_CONFLICT`。撤销针对显示的偏好 ID，旧任务和历史摘要不能重新写入已经删除的偏好。

偏好键为 `count|topic|questionType|direction`，题数限制 1–20，文本最长 500 字符。意图变更必须带当前输入逐字依据 `instructionQuote` 和显式作用范围；不符合依据或版本不符时跳过写入。撤销保留不含原值的版本墓碑，阻止旧输入恢复偏好；集合删除时清理没有来源的记录。

优先级为当前明确指令 > 本轮要求 > 长期偏好 > 默认值。提交任务固定事实快照、当前题、回答版本、消息边界和偏好版本；界面编辑不改变已提交任务输入。删除材料集合级联清理消息、短期记忆、摘要、事实快照、任务及偏好来源；无其他来源的偏好删除。取消或删除后 Worker 不得发布成功结果。

## 阶段八：历史对话管理契约（已实现）

本节接口已实现并通过 HTTP 集成验收。全部路径以 `/api/v1` 为前缀，管理操作均不调用 LLM。

| 方法 | 路径 | 成功状态 | 目标行为 |
|---|---|---:|---|
| GET | `/material-sets/{id}/conversations` | 200 | 扩展历史筛选，范围包含集合所有材料版本 |
| PATCH | `/conversations/{id}` | 200 | 原子更新标题、置顶、分组和归档状态 |
| DELETE | `/conversations/{id}` | 204 | 删除对话及关联数据，重复删除仍返回 204 |
| GET | `/material-sets/{id}/conversation-groups` | 200 | 返回单层分组数组 |
| POST | `/material-sets/{id}/conversation-groups` | 201 | 创建集合内分组 |
| PATCH | `/conversation-groups/{id}` | 200 | 重命名分组 |
| DELETE | `/conversation-groups/{id}` | 204 | 对话转未分组；重复删除仍返回 204 |

列表查询参数：`status=active|archived|all`（默认 `all`，兼容旧调用者）；`q` 为可选标题字面子串，去空白后最长 200 字符、大小写不敏感；可选 `groupId` 为具体分组 ID 或 `ungrouped`。各过滤条件取交集，具体分组必须属于目标集合。

列表继续返回现有数组，对话对象保留既有字段，增加 `groupId`、`isPinned`、`pinnedAt`、`isArchived`、`archivedAt`、`lastActivityAt`。详情 `GET /conversations/{id}` 同样增量返回管理字段，归档后可正常读取。

日常客户端显式请求 `status=active`；归档入口请求 `status=archived`；标题搜索及删除集合前获取完整 ID 清单请求 `status=all`。列表按置顶优先、置顶时间倒序、非置顶最近练习时间倒序、ID 升序排序；前端组织为置顶和分组区域，禁止重复展示。

PATCH 示例：

```json
{
  "title": "Redis 专项练习",
  "isPinned": true,
  "groupId": null,
  "isArchived": false
}
```

字段全部可选，但至少提供一个；只更新出现的字段。标题去空白后长度 1–200；布尔字段和标题不接受 null；`groupId:null` 清除归属。重复设置置顶/归档不改变对应时间，取消时清空时间。跨集合分组和组合请求中的任何非法字段均导致整次更新回滚。

分组创建/更新请求为 `{ "name": "项目专项" }`；响应含 `id`、`materialSetId`、`name`、`createdAt`、`updatedAt`。名称去空白后长度 1–80，同集合去空白及大小写折叠后唯一，禁止使用“置顶”“未分组”“已归档”。列表按创建时间及 ID 升序返回，包含空组。

| HTTP | 稳定 code | 触发条件 |
|---|---|---|
| 404 | `CONVERSATION_NOT_FOUND` | 对话读取/更新目标不存在 |
| 404 | `CONVERSATION_GROUP_NOT_FOUND` | 分组读取/更新目标不存在 |
| 409 | `CONVERSATION_GROUP_SCOPE_MISMATCH` | 对话或筛选关联其他集合的组 |
| 409 | `CONVERSATION_GROUP_NAME_CONFLICT` | 同集合分组名冲突 |
| 422 | `CONVERSATION_HISTORY_INVALID` | 空更新、非法标题/组名/过滤条件等管理输入 |
| 409 | `CONVERSATION_BUSY` | queued/running 任务期间归档或单独删除 |
| 409 | `CONVERSATION_ARCHIVED` | 向归档对话提交内容或重试任务 |

所有错误使用 Problem Details。归档写保护覆盖自然语言输入、问题生成、回答、反馈、参考答案、追问、导航、任务重试、旧同步消息和补充确认；读取与管理允许。忙碌判断与归档/删除必须事务协调，任务取消后的迟到结果不得回写。

单独删除移除消息、短期记忆/摘要/快照、练习与任务、候选人补充和偏好来源；无其他来源的偏好删除。材料版本及原始证据、其他对话的既有快照保留；材料版本级共享代码快照不因单独删除清理。材料集合删除仍清理普通及归档对话和分组。
