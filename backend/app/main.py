from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .common.errors import AppError
from .controller.api_v1 import router as api_v1_router
from .db import init_db


app = FastAPI(title="简历面试助手 API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    trace_id = request.headers.get("X-Request-Id")
    return JSONResponse(status_code=exc.status, content=exc.problem(trace_id), media_type="application/problem+json", headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    field_errors: dict[str, list[str]] = {}
    for error in exc.errors():
        location = error.get("loc", [])
        field = str(location[-1]) if location else "request"
        field_errors.setdefault(field, []).append(error.get("msg", "参数无效"))
    body = {"type": "about:blank", "title": "Validation failed", "status": 422, "detail": "请求参数校验失败", "code": "VALIDATION_ERROR", "fieldErrors": field_errors}
    return JSONResponse(status_code=422, content=body, media_type="application/problem+json")


app.include_router(api_v1_router)
