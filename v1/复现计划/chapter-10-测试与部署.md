# 第 10 章：测试与部署

## 本章目标

为后端核心模块编写测试，将项目部署到公网，让 Web 和小程序可以访问。

## 前置知识

- pytest 基本用法（`assert`、`@pytest.fixture`）
- pytest monkeypatch（模拟环境变量）
- 什么是 PaaS 部署（Render / Railway 等平台）
- Web 服务器和 ASGI 是什么

---

## Part A：写测试

### Step 1：测试配置

`backend/pytest.ini`：
```ini
[pytest]
pythonpath = .
```

### Step 2：核心测试清单

按优先级排列：

#### 测试 1：健康检查（最基础）

```python
# tests/test_health.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_returns_ok():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

#### 测试 2：推荐接口（核心链路）

```python
# tests/test_recommend.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_recommend_returns_three_shops():
    resp = client.post("/api/v1/recommend", json={
        "query": "清水河，一个人吃清淡的",
        "top_k": 3,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "recommendations" in data
    assert len(data["recommendations"]) <= 3
    assert "parsed" in data
    assert "meta" in data

def test_recommend_empty_query_rejected():
    resp = client.post("/api/v1/recommend", json={"query": ""})
    assert resp.status_code == 422  # Pydantic validation error

def test_recommend_different_queries_give_different_results():
    r1 = client.post("/api/v1/recommend", json={"query": "清水河 清淡", "top_k": 3}).json()
    r2 = client.post("/api/v1/recommend", json={"query": "沙河 麻辣 聚餐", "top_k": 3}).json()
    names1 = [r["name"] for r in r1["recommendations"]]
    names2 = [r["name"] for r in r2["recommendations"]]
    assert names1 != names2, "不同的 query 应该返回不同结果"
```

#### 测试 3：解析器（单元测试）

```python
# tests/test_parser.py
from app.services.parser import parse_query

def test_parse_budget():
    slots = parse_query("预算25，吃面")
    assert slots.budget_max == 25

def test_parse_location():
    slots = parse_query("清水河附近有什么好吃的")
    assert slots.location == "清水河"

def test_parse_scene():
    slots = parse_query("一个人吃饭")
    assert slots.scene == "一个人"

def test_parse_taste():
    slots = parse_query("想吃清淡的")
    assert slots.taste == "清淡"
```

#### 测试 4：JWT（安全相关，必须测）

```python
# tests/test_auth.py
from app.services.auth_token_service import issue_access_token, verify_access_token, AuthTokenError
import pytest

def test_token_roundtrip():
    token = issue_access_token("user_123")
    claims = verify_access_token(token)
    assert claims["sub"] == "user_123"

def test_expired_token_rejected(monkeypatch):
    import time
    monkeypatch.setenv("WECHAT_AUTH_TOKEN_TTL_SECONDS", "0")  # 立即过期
    token = issue_access_token("user_123")
    time.sleep(1)
    with pytest.raises(AuthTokenError):
        verify_access_token(token)

def test_bad_signature_rejected():
    token = issue_access_token("user_123")
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.badsignature"
    with pytest.raises(AuthTokenError):
        verify_access_token(tampered)
```

#### 测试 5：输出清洗（Spark 模式核心防线）

```python
# tests/test_spark_sanitize.py
from app.services.spark_local_recommend_service import _sanitize_or_fallback

CANDIDATES = [
    {"name": "学子餐厅", "score": 0.85},
    {"name": "老麻抄手", "score": 0.72},
]

def test_valid_output_passes():
    raw = '{"recommendations": [{"name": "学子餐厅", "reason": "适合你", "match_score": 0.9}]}'
    result = _sanitize_or_fallback(raw, CANDIDATES)
    assert result["recommendations"][0]["name"] == "学子餐厅"

def test_hallucinated_name_filtered():
    """LLM 编造的店名被过滤"""
    raw = '{"recommendations": [{"name": "银杏餐厅", "reason": "不错", "match_score": 0.9}]}'
    result = _sanitize_or_fallback(raw, CANDIDATES)
    assert result["engine"] == "rule-based-fallback"

def test_malformed_json_fallsback():
    raw = "这不是JSON"
    result = _sanitize_or_fallback(raw, CANDIDATES)
    assert result["engine"] == "rule-based-fallback"
```

### Step 3：运行测试

```bash
cd backend
python -m pytest tests/ -v

# 只跑推荐相关测试
python -m pytest tests/test_recommend.py -v

# 显示测试覆盖率（需安装 pytest-cov）
pip install pytest-cov
python -m pytest tests/ --cov=app --cov-report=term-missing
```

---

## Part B：部署

### 方案一：Render（最简单）

Render 是免费的 Python Web 服务部署平台，适合这个项目。

**步骤**：

1. 在项目根目录创建 `render.yaml`：
```yaml
services:
  - type: web
    name: chedian-eat-backend
    env: python
    buildCommand: cd backend && pip install -r requirements.txt
    startCommand: cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: CORS_ALLOW_ORIGINS
        value: "*"
      - key: RECOMMEND_PROVIDER
        value: workflow
      - key: XFYUN_API_KEY
        sync: false
      - key: XFYUN_API_SECRET
        sync: false
      - key: AUTH_TOKEN_SECRET
        generateValue: true
```

2. Push 到 GitHub
3. 在 Render 控制台 → New Web Service → 连接你的仓库
4. Render 自动检测 `render.yaml` 并部署

部署后的 URL 类似：`https://chedian-eat-agent-mvp.onrender.com`

### 方案二：Vercel（前端）+ Render（后端）

```bash
# 前端部署到 Vercel（免费）
cd frontend
npx vercel

# 部署时设置环境变量
# NEXT_PUBLIC_API_BASE_URL=https://your-backend.onrender.com
```

### 部署后要改的配置

| 位置 | 改什么 |
|---|---|
| `frontend/.env.local` | `NEXT_PUBLIC_API_BASE_URL` 改为生产 URL |
| `miniprogram/utils/config.js` | `PROD_BASE_URL` 改为生产 URL，`FORCE_REMOTE_IN_DEV` 设为 `true` |
| 微信小程序后台 | 添加后端域名到 `request 合法域名` 列表 |
| 后端 `.env` | `CORS_ALLOW_ORIGINS` 加入前端域名 |

### 部署验证清单

- [ ] `GET /api/v1/health` 返回 `200`
- [ ] Swagger 文档能打开（`/docs`）
- [ ] Web 前端能正常搜索并展示推荐结果
- [ ] 小程序真机上能正常访问
- [ ] HTTPS 正常（无混合内容警告）

---

## 测试策略总结

| 优先级 | 测什么 | 为什么 |
|---|---|---|
| P0 | 推荐接口 200 + 返回格式正确 | 核心功能崩了就是事故 |
| P0 | JWT 签发/验证/过期 | 安全相关，出 bug 影响所有鉴权 |
| P1 | 解析器各槽位提取 | 规则引擎的输入如果解析错了，推荐全错 |
| P1 | Spark 输出清洗 | LLM 幻觉是已知问题 |
| P2 | 反馈/收藏 CRUD | 辅助功能，错了用户可重试 |
| P3 | 广告/排行 | 展示类功能，错了不会阻塞核心流程 |

## 章末检查

- [ ] 至少 5 个核心测试通过
- [ ] 测试覆盖推荐、解析、JWT、输出清洗 4 个关键模块
- [ ] 后端部署到公网并验证 `/api/v1/health` 可访问
- [ ] 前端部署后能正常调用后端
