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

`selection` 可以为 `null`。助手响应必须保留结构化 `questions`、`evidence`、`inferenceDrafts`、`evidenceGaps` 和 `feedback`。

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
