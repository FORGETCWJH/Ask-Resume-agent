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

文档/LLM 的旧 `app/services/` 模块目前由 `app/infrastructure/ingestion.py` 和 `app/infrastructure/llm.py` 作为兼容适配入口导出；业务用例只从 `infrastructure` 入口依赖，后续可在不改动 service 层的情况下替换具体实现。

## 前端

```text
pages -> features -> api
                  -> types
components <- features
```

页面只组合业务模块；业务模块管理查询、变更和交互；HTTP 细节集中在 `api/`；通用组件不依赖材料集合或对话业务。

## 事务和版本

上传创建新的不可变材料版本。对话创建时记录 `revisionId`，后续替换或删除材料不影响旧对话。单份材料删除由 service 创建排除目标材料的新当前版本；删除材料集合使用一个服务用例级联清理数据库和本地文件。
