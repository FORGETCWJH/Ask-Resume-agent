"""仅用于浏览器验收：在外部 LLM 边界注入延迟和失败，业务服务保持真实。"""
import asyncio
import os
import sys
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.infrastructure.llm import FakeLLMClient, LLMError
from app.service import practice_service, agent_follow_up_service
from app.main import app
import uvicorn


class BrowserScenarioLLM(FakeLLMClient):
    failed_revisions = set()

    async def structured(self, **kwargs):
        if kwargs["mode"] == "practiceIntent":
            if kwargs["user_text"] == "测试取消等待":
                await asyncio.sleep(3)
            revision = re.search(r'"revisionId": "([^"]+)"', kwargs["context"]).group(1)
            if kwargs["user_text"] == "测试模型失败" and revision not in self.failed_revisions:
                self.failed_revisions.add(revision)
                raise LLMError("浏览器测试：模型暂时不可用")
        return await super().structured(**kwargs)


if __name__ == "__main__":
    if settings.llm_api_key:
        raise SystemExit("浏览器测试服务器必须使用空 LLM_API_KEY")
    llm = BrowserScenarioLLM()
    practice_service.get_llm_client = lambda: llm
    agent_follow_up_service.get_llm_client = lambda: llm
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("BROWSER_SERVER_PORT", "8000")))
