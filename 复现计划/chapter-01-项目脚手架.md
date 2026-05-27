# 第 1 章：项目脚手架

## 本章目标

创建一个最小可运行的 FastAPI 项目——只有一个 `/health` 端点，能访问 Swagger 文档，配置好 CORS 和 UTF-8 编码。

## 前置知识

- Python 虚拟环境是什么（venv）
- `pip install` 怎么用
- FastAPI 是什么（知道它是个 Python Web 框架即可）

## 文件清单

```
backend/
├── .env                    # 环境变量（密钥等敏感信息放这）
├── .env.example            # .env 的模板（不含真实密钥，可提交 git）
├── .python-version         # 固定 Python 版本：3.11
├── requirements.txt        # 依赖清单
├── pytest.ini              # 测试配置
└── app/
    ├── __init__.py
    ├── main.py             # ★ 应用入口
    ├── api/
    │   └── __init__.py
    ├── models/
    │   └── __init__.py
    ├── services/
    │   └── __init__.py
    └── core/
        └── __init__.py
```

## 逐步实现

### Step 1：创建目录结构

```bash
mkdir -p backend/app/{api,models,services,core}
```

每个目录下放一个空的 `__init__.py`，让 Python 把它们当成包。

### Step 2：固定 Python 版本

创建 `backend/.python-version`：
```
3.11
```

创建 `backend/runtime.txt`：
```
python-3.11.11
```

**为什么？** 锁定版本防止你和队友 / 服务器环境不一致导致的神秘 bug。

### Step 3：写 requirements.txt

```txt
fastapi==0.116.1
uvicorn==0.35.0
pydantic==2.11.7
python-dotenv==1.0.1
httpx==0.28.1
python-multipart==0.0.20
pytest==9.0.2
PyYAML==6.0.2
```

每个包的作用：

| 包 | 干什么的 |
|---|---|
| fastapi | Web 框架 |
| uvicorn | ASGI 服务器（把 FastAPI 跑起来） |
| pydantic | 数据校验（请求/响应格式的定义和检查） |
| python-dotenv | 自动读取 .env 文件 |
| httpx | 发 HTTP 请求（调外部 API 用） |
| python-multipart | 文件上传支持 |
| pytest | 测试框架 |
| PyYAML | 读 YAML 配置文件 |

### Step 4：创建 .env 和 .env.example

`backend/.env.example`（提交到 git）：
```env
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

`backend/.env`（不提交到 git，放你自己真实的密钥）：
```env
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

在 `.gitignore` 中确保 `.env` 被忽略。

### Step 5：写 main.py —— 整个项目的入口

```python
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

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


# ===== 健康检查 =====
@app.get("/api/v1/health")
def health():
    return {"status": "ok"}
```

**为什么有两个中间件？**

- **CORS 中间件**：浏览器安全策略禁止 `localhost:3000`（前端）直接请求 `localhost:8000`（后端），CORS 就是告诉浏览器"允许这个来源访问我"
- **UTF-8 中间件**：不加 `charset=utf-8`，部分浏览器/客户端中文会变 `???`（mojibake）。这个项目全程中文交互，这是血的教训换来的

### Step 6：安装依赖并启动

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows 用 venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 验证方法

1. 打开 `http://localhost:8000/docs`，应该看到 Swagger 自动生成的 API 文档页面
2. 点 `/api/v1/health` → "Try it out" → "Execute"，返回 `{"status": "ok"}`
3. 用 curl 验证中文不乱码：
   ```bash
   curl -i http://localhost:8000/api/v1/health
   # 应该看到 Content-Type: application/json; charset=utf-8
   ```

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError: No module named 'app'` | 没在 backend 目录下启动 | 确保终端在 `backend/` 目录 |
| 前端 fetch 报 CORS 错误 | CORS 没配置对 | 检查前端端口是否在 `allow_origins` 里 |
| 中文变成 `???` | 缺少 UTF-8 中间件 | 确认 `Utf8ResponseMiddleware` 已注册 |
| `.env` 不生效 | `load_dotenv` 路径不对 | 检查 `parents[1]` 是否指向 backend 目录 |

## 章末检查

- [ ] `uvicorn app.main:app --reload --port 8000` 启动成功
- [ ] `http://localhost:8000/docs` 能打开
- [ ] `/api/v1/health` 返回 `{"status": "ok"}`
- [ ] 响应头包含 `charset=utf-8`
