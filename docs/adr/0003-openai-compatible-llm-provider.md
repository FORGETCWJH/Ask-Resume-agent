# ADR 0003：使用可配置的 OpenAI-compatible Chat Completions 适配器

## 状态

已接受

## 背景

MVP 需要直接向外部模型发起对话，但不同供应商对 Base URL、鉴权 Header、JSON 输出约束和临时错误的支持存在差异。把供应商 SDK 写进业务服务会增加替换成本，也会让测试依赖真实网络。

## 决策

后端使用 `httpx` 调用 OpenAI-compatible `POST /chat/completions`，并通过环境变量配置模型标识、响应格式、鉴权模式、输出上限、温度、超时和重试次数。

默认使用 `Authorization: Bearer <key>` 和 `response_format: {"type":"json_object"}`。只对网络错误、429 和 5xx 做有限重试；测试套件自动关闭外部模型调用并使用演示响应。

## 取舍

这保留了供应商可替换性，也便于验证结构化响应；代价是无法利用某个供应商的专有 SDK 能力。MVP 暂不接入工具调用、流式输出或供应商专属 Responses API。
