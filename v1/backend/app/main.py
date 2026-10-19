import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router
from app.api.proxy_routes import proxy_router

# 自动加载 backend/.env
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)

app = FastAPI(title="成电吃什么 Agent API", version="0.1.0")


# ===== UTF-8 中间件 =====
class Utf8ResponseMiddleware(BaseHTTPMiddleware):
    """确保所有 JSON 响应的 Content-Type 包含 charset=utf-8"""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json") and "charset=" not in content_type.lower():
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response


# ===== CORS 配置 =====
raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
if raw_origins:
    allow_origins = [item.strip() for item in raw_origins.split(",") if item.strip()]
else:
    allow_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(Utf8ResponseMiddleware)


# ===== 挂载路由 =====
app.include_router(router, prefix="/api/v1", tags=["mvp"])
app.include_router(proxy_router, prefix="/api", tags=["deepseek-proxy"])


# ===== 启动事件 =====
@app.on_event("startup")
def startup():
    from app.services.ad_repository import seed_default_ads
    seed_default_ads()
