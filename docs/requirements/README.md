# 需求文档

本目录是简历面试助手的需求文档唯一存放位置。

## 阅读规则

- 修改简历上传、PDF/DOCX 解析、OCR、结构化识别、识别结果表单或确认流程前，先阅读对应需求文档。
- 需求发生变化时，先更新本目录中的需求文档，再同步更新 `CONTEXT.md`、功能链路和开发计划。
- 需求文档描述目标行为；已实现接口和代码细节分别以 `docs/api/`、架构文档和代码为准。

## 文档索引

- [简历识别与确认](./resume-recognition.md)：从上传简历到 OCR、模块识别、人工修正、确认入库的完整需求。
- [阶段一：OCR 简历提取与确认](./ocr-resume-extraction.md)：当前只实现本地解析、OCR、结构化草稿和人工确认，不调用 LLM。
- [Agent 追问与项目参考答案](./agent-follow-up.md)：问题范围、问题版本、异步 LLM 任务、只读代码检索、参考答案和反馈闭环。
- [对话式练习、意图识别与记忆](./conversation-practice.md)：阶段七已实现，统一输入框、顶部简历、自然语言动作与记忆；配套[开发计划](../plans/CONVERSATION_PRACTICE_PLAN.md)。
- [历史对话管理](./conversation-history.md)：阶段八已实现并验收；置顶、单层分组、归档/恢复、重命名、标题搜索和单独删除；配套[开发计划](../plans/CONVERSATION_HISTORY_PLAN.md)。
