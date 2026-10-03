# GPT-6 Sol token limit 研究

检索日期：2026-09-27（Asia/Shanghai）

## 结论

- OpenAI 官方模型页对 `gpt-6-sol` 的公开规格是：上下文窗口 **1,050,000 tokens**，最大输出 **128,000 tokens**。该最大输出是模型规格上限；实际请求仍会受到输入长度、请求参数、账户/组织限流和提供商网关策略影响。
- OpenAI Responses API 使用 `max_output_tokens` 设置生成上限。官方定义为可选的 number/null，最小值为 16；上限同时计算可见输出 token 和 reasoning token。Responses API 文档没有把 `max_tokens` 列为该请求参数。
- OpenAI Chat Completions API 使用 `max_completion_tokens` 表示包含可见输出和 reasoning token 的生成上限。`max_tokens` 已标记为 deprecated，官方说明应改用 `max_completion_tokens`，且不兼容 reasoning（官方文档称 o-series）模型。不要把 `max_tokens` 当成 GPT-6 Sol 的推荐参数。
- OpenAI-compatible 网关通常只返回基础模型元数据，未必提供 context window、max output 或参数上限字段。因此具体网关的独立限制 **不能仅从模型列表推断**。
- 对兼容网关的最小请求只能说明某个参数被接受，不能证明它被严格执行，也不能推导网关的实际最大值。探测结果不替代供应商规格，也不应作为稳定契约。
- 若供应商没有公开 OpenAPI 或参数规格，应以书面规格或受控环境验证为准，并在运行时处理 `finish_reason`、错误响应和实际 usage。

## 来源

1. OpenAI 官方模型规格：[GPT-6 Sol Model](https://developers.openai.com/api/docs/models/gpt-6-sol)（页面显示 `1,050,000 context window`、`128,000 max output tokens`、reasoning token support）。
2. OpenAI 官方 Responses API 创建接口：[Responses - Create](https://developers.openai.com/api/reference/resources/responses/methods/create)（`max_output_tokens` 的类型、最小值 16，以及包含 visible/reasoning tokens 的定义）。
3. OpenAI 官方 Chat Completions 创建接口：[Chat Completions - Create](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)（`max_completion_tokens` 定义及 `max_tokens` deprecated/不兼容 reasoning 模型的说明）。
4. OpenAI-compatible 网关的模型列表和模型元数据接口：用于确认模型是否可用，但不能假定其完整 token 限制。
5. 供应商提供的 API 参数文档或书面规格：应优先作为网关限制的事实来源。
6. 受控环境中的最小请求与运行时 usage：只能用于补充验证，不能替代供应商规格。

## 适用边界

上述 1,050,000 / 128,000 是 OpenAI 官方 `gpt-6-sol` 页面规格，不等于任何 OpenAI-compatible 网关一定放行的限制。网关可能设置更小的请求、账户、并发或计费上限。应用若要依赖具体上限，应取得供应商书面规格或在受控环境中按需验证，并对 `finish_reason`、错误响应和实际 usage 做运行时处理。

本记录不包含任何 API key、Authorization 值或其他凭据。
