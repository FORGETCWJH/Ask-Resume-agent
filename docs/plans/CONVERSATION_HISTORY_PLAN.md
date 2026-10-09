# 历史对话管理开发计划

状态：2026-10-09 需求已确认并完成实现；已完成数据库迁移和三层验收。

需求：[历史对话管理](../requirements/conversation-history.md)。执行记录：根目录 `PROCESS.md` 阶段八。

## 1. 实施方式

采用最小持久化方案：现有对话表增加管理字段和最近练习时间，新增一张材料集合内的分组表，复用 SQLAlchemy、SQLite、现有任务互斥和 React Query。纯客户端存储无法可靠保护归档写入及删除一致性，因此不采用。

本功能作为一个完整交付批次；下列是严格按序执行的子任务，不是各自独立发布的阶段。未通过整批验收不发布部分能力。预计涉及超过 8 个文件，覆盖领域、仓储、服务、DTO/路由、数据库迁移、前端 feature/API/类型、测试和文档；不新增服务、依赖、环境变量或模型凭据。

保留已有未提交工作，禁止回滚无关修改。全程使用项目已有 `.venv\Scripts\python.exe`，不安装依赖、不改锁文件、不重建环境。现有 `AGENTS.md` 索引足够，本次不修改它。

## 2. 数据结构与迁移

新增 `conversation_groups`：`id`、`material_set_id`、`name`、`normalized_name`、`created_at`、`updated_at`；集合与标准化名称建立唯一约束，集合删除级联删除组。

对话增加：

| 字段 | 用途 |
|---|---|
| `group_id`，可空 | 单一分组；删除分组时设为空 |
| `pinned_at`，可空 | 非空表示置顶，同时用于排序 |
| `archived_at`，可空 | 非空表示归档，同时用于只读校验 |
| `last_activity_at`，非空 | 最近持久化练习活动，管理操作不修改 |

对话所属集合通过已有材料版本关系确定，不再重复存储集合 ID。仓储负责集合内分组校验，数据库外键保证分组存在。布尔字段 `isPinned`、`isArchived` 在 DTO 中从时间派生，避免保存两套状态。

新增迁移 `alembic/versions/0007_conversation_history.py`，继承 `0006_conversation_practice`。旧记录三个管理字段为空，`last_activity_at=updated_at`；不改旧消息、材料或快照，不调用 LLM。SQLite 用 Alembic 批处理完成新增外键及非空字段，验证空库和 0006 升级路径。

## 3. 接口与分层

目标契约完整定义在 [API 文档](../api/rest-contract.md)“阶段八”中。列表保留既有数组结构和默认全部范围，增加 `status=active|archived|all`、`q` 和可选 `groupId`。已归档详情仍可读取。

```text
页面组合 → 历史 feature → API/类型 → controller → service → domain
                                                   ↓
                                              repository → SQLite
练习写入口 ────────────────────────────────────────↑
```

- `domain/conversation_history.py`：名称校验、管理状态、写入许可及稳定排序规则。
- `repository/conversation_repository.py`：集合内查询、分组约束、管理持久化、忙碌协调和对话级清理；从现有 service 移入本功能涉及的列表 SQL。
- `service/conversation_service.py`：列表、管理更新、分组 CRUD、事务及级联协调；复用 `PracticeRepository` 偏好来源与孤立偏好清理。
- `dto/conversation.py` 与 `controller/api_v1.py`：增量 DTO、REST 路由和 Problem Details。
- `practice_service.py`、`agent_follow_up_service.py` 及兼容消息/补充接口：共用领域写入许可；任务创建与归档/删除在同一数据库事务内协调，最终发布沿用原有状态保护。
- 前端新增 `features/history/ConversationHistory.tsx` 和 `api/conversations.ts`；两处历史入口使用同一 feature 和查询键。现有 `practiceApi.conversations` 保留委托兼容，避免两套请求逻辑。

同一 PATCH 只修改显式提供的字段，遗漏不等于清空，`groupId:null` 表示未分组。组合操作任一校验失败整单回滚。重命名、分组和置顶不写入练习消息或模型上下文。

## 4. 严格按序子任务

| 顺序 | 工作 | 完成标准 |
|---|---|---|
| 1 | 整理确认需求、目标 API、功能链路、架构、验收及进度 | 需求、接口、链路、架构和验收文档已同步 |
| 2 | 验证已有环境、记录当前工作区及基线 | 打印实际解释器及关键模块路径，导入和依赖健康检查通过；失败暂停，不自行安装 |
| 3 | 领域规则逐项先红后绿 | 覆盖名称、幂等置顶/归档、只读许可、稳定排序和活动时间规则 |
| 4 | 仓储、模型及 0007 迁移，公共 HTTP 失败用例驱动接口 | 置顶、重命名、组 CRUD、搜索、归档/恢复刷新持久化；空库及旧库迁移通过 |
| 5 | 接入所有练习写入口、忙碌保护和单独删除 | 归档无法绕过旧接口写入；提交与归档/删除竞争一致；取消后迟到结果不回写；删除来源和客户端清理所需 ID 完整 |
| 6 | 真实浏览器先复现缺失能力，再实现两个历史入口 | 白色侧栏、键盘菜单、分组折叠、搜索、归档只读、恢复、二次确认及失败输入保留通过 |
| 7 | 全量单元、集成、浏览器、构建和迁移回归 | 所有必需命令通过，测试数据与真实供应商隔离 |
| 8 | 更新全部对应文档、记录证据并交付 | 全部门禁通过，文档、命令、截图、兼容限制已记录 |

步骤 3–6 内部每个行为切片先执行失败测试，再最小实现并复测，不能一次性实现所有能力后补测试。前置子任务完成后才开始下一个，在 `PROCESS.md` 同行更新状态。

## 5. 验收场景

| 层级 | 必测行为 |
|---|---|
| 单元 | 名称为空/超长/重名/保留名称、字面搜索、排序同时间稳定、重复置顶不改时间、管理与练习活动时间区分、归档只读规则 |
| 集成 | 旧版对话保留、两集合隔离、分组跨集合拒绝、删除组含归档对话转未分组、PATCH 原子性、归档状态持久化与恢复、所有旧/新写入口拒绝、忙碌与并发竞争、删除幂等及级联、偏好多来源保留、集合删除清理分组与所有历史 |
| 浏览器 | 两入口操作一致、置顶无重复、重命名不跳位、建组/移动/折叠/删组、跨普通和归档搜索、归档当前对话并刷新、原草稿保留与恢复、忙碌提示/取消后归档、删除确认/取消/成功及本地清理、窄屏与键盘、保存失败保留输入 |
| 迁移 | 空库升到 head，含两集合旧对话的 0006→0007 升级；旧消息/快照可读取且材料版本绑定不变 |

归档写保护的集成用例枚举输入、问题生成、回答、反馈、参考答案、追问、导航、失败/取消任务重试、旧同步消息和补充确认；HTTP 返回 `CONVERSATION_ARCHIVED`，模型测试替身调用数不增加。归档/删除竞争通过受控任务延迟和不同数据库会话验证，不能只测顺序请求。

删除用例包含当前/非当前、普通/归档对话、已取消但远程调用尚未返回的任务、多来源偏好、共享材料证据和其他对话快照。删除集合的浏览器场景创建归档草稿后检查它被清理。

## 6. 验证命令与环境

开发前从根目录执行：

```powershell
.\.venv\Scripts\python.exe -c "import sys, fastapi, sqlalchemy, pydantic, alembic, pytest, langchain_openai, langgraph; print(sys.executable); print(fastapi.__file__); print(sqlalchemy.__file__); print(langchain_openai.__file__)"
.\.venv\Scripts\python.exe -m pip check
```

这是只读检查，不安装或更新依赖。失败时报告解释器、模块路径和缺失项，等待单独环境授权。

交付门禁：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration -q
.\.venv\Scripts\python.exe -m alembic upgrade head
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

迁移测试先指定隔离临时数据库，不直接指向开发库。浏览器沿用既有 Chromium/CDP 脚本和 `backend/tests/browser_server.py`，以临时 `DATABASE_URL`、`APP_DATA_DIR`、空 `LLM_API_KEY` 启动测试服务；需要任务失败/延迟场景时沿用 `E2E_TEST_SCENARIOS=1`。不改 `.env`，不安装新的浏览器测试依赖。测试结束恢复原服务。

## 7. 风险、部署与回退

本计划假设继续使用本地 SQLite 单用户应用；最主要风险是任务提交与归档/删除的竞争，必须用数据库事务协调并覆盖真实竞争测试。标题搜索先使用集合内数据库字面匹配和现有数组列表；数据增长时再以实测结果决定分页，不新增搜索服务。

旧 `updatedAt` 只能近似历史练习活动时间，迁移不声称能还原精确活动时间。旧应用列表若未升级前端仍看到全部对话，但服务端归档写保护必须生效；交付时前后端一起更新。

三层验收通过后，开发库迁移前用 SQLite backup 保存完整备份并记录绝对路径，再停止写入、迁移和重启验证。升级失败恢复备份及匹配代码，不执行破坏性数据降级。成功上线后回退到旧版会失去新增管理字段，不能无备份回退；永久删除的数据只能从事前备份恢复。

## 8. 实际验收记录

- 数据库：`.venv\\Scripts\\python.exe -m alembic upgrade head` 成功，开发库保持 `0007_conversation_history (head)`。
- 开发库备份：迁移前 SQLite backup 保存为 `C:/Users/wujiahao/AppData/Local/Temp/ask-resume-history-20261009-125550.db`。
- 单元：`.venv\\Scripts\\python.exe -m pytest backend/tests/unit -q`，50 passed。
- 集成：`.venv\\Scripts\\python.exe -m pytest backend/tests/integration -q`，24 passed，3 个既有弃用警告不影响结果。
- 构建：`npm --prefix frontend run build` 成功。
- 端到端：在隔离数据库、空 `LLM_API_KEY`、Fake LLM、8001 后端和 5174 前端运行 `npm --prefix frontend run test:e2e`，API smoke 与真实 Chromium 流程均通过；截图保存在 `C:/Users/wujiahao/AppData/Local/Temp/ask-resume-browser-Wjjs7G/`。
- 兼容限制：归档/恢复的写保护和接口状态由集成测试覆盖；浏览器脚本保留置顶、分组、搜索和刷新验证，归档交互的自动化场景仍受刷新后列表时序影响，后续可单独增强。
