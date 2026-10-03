# 简历面试助手

这是一个面向 Python 后端求职者的本地 MVP：上传简历和真实项目材料，基于证据生成问题，找出理解缺口，并练习回答面试追问。

## 启动后端

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

已有数据库升级识别表：

```powershell
alembic upgrade head
```

没有配置 `LLM_API_KEY` 时，应用使用本地演示响应，方便验证上传、证据和对话流程；接入真实模型时，在项目根目录创建 `.env`：

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-server-side-key
LLM_MODEL=gpt-4o-mini
LLM_RESPONSE_FORMAT=json_object
LLM_AUTH_MODE=bearer
LLM_API_KEY_HEADER=Authorization
LLM_MAX_OUTPUT_TOKENS=64000
LLM_TEMPERATURE=0.2
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=1
```

OpenAI-compatible 服务的 `LLM_BASE_URL` 填 API 根地址，代码会自动请求 `/chat/completions`。例如：`https://example.com/v1`。真实密钥只放在本地 `.env`，不要提交到仓库。

## 启动前端

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

打开 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)。后端健康检查地址为 [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)。

接口契约位于 `docs/api/rest-contract.md`。外部 JSON 使用 camelCase，错误响应使用 Problem Details；旧 `/api` 路径不再新增功能。

## 当前能力

- PDF/DOCX 简历解析，图片型 PDF 使用 OCR 兜底
- 简历个人信息、技能、工作/实习经历和项目经验结构化识别
- 识别草稿表单编辑、分区确认和原文证据定位
- ZIP 项目静态读取，跳过依赖、构建产物和二进制文件
- 材料证据索引和页码/文件路径定位
- 选中证据提问、生成问题、候选人回答和反馈
- 本地 SQLite 和文件目录存储
- 完整删除材料集合及派生数据

简历识别需求详见 `docs/requirements/resume-recognition.md`；未确认的识别草稿不会作为对话事实证据。

MVP 暂不执行上传代码，也不实现自主 Agent 工具循环。

## 测试门禁

```powershell
pytest backend/tests/unit -q
pytest backend/tests/integration -q
cd frontend
npm run test:e2e
```

跨前后端、上传解析、对话、数据库契约或删除链路的修改必须通过全部三层测试。
