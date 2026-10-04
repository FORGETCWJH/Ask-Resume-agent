# ADR 0003：使用可配置的 OpenAI-compatible Chat Completions 适配器

## 状态

已接受

## 背景

MVP 需要直接向外部模型发起对话，但不同供应商对 Base URL、鉴权 Header、JSON 输出约束和临时错误的支持存在差异。把供应商 SDK 写进业务服务会增加替换成本，也会让测试依赖真实网络。

## 决策

后端使用 `langchain-openai` 的 `ChatOpenAI` 调用 OpenAI-compatible 服务，并通过环境变量配置 base URL、模型标识、鉴权、输出上限、温度、超时和重试次数。应用层不直接创建 `httpx.AsyncClient`。

默认使用 `json_mode + Pydantic` 校验结构化结果。适配器只处理同一次调用的技术性错误，任务层负责显式重试；测试套件自动关闭外部模型调用并使用 Fake LLM 响应。

## 取舍

这保留了供应商可替换性，也便于统一结构化响应和 LangGraph 节点；代价是增加 LangChain 依赖。MVP 暂不接入工具调用、流式输出或供应商专属 Responses API。
