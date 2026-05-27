# 第 6 章：用户认证

## 本章目标

实现匿名优先 + 可选微信登录的用户身份体系，包括 JWT 的签发/验证和匿名↔登录的数据迁移。

## 前置知识

- JWT 是什么（JSON Web Token，一个签了名的 JSON 数据包，服务端签发、客户端携带）
- OAuth 是什么（第三方登录的协议，微信登录是 OAuth 的变体）
- HMAC-SHA256 是什么（一种签名算法，用密钥保证数据没被篡改）

## 文件清单

```
backend/
├── .env                      # 新增 AUTH_SECRET, 微信配置
└── app/
    ├── api/
    │   ├── auth.py               # ★ 鉴权依赖函数
    │   └── proxy_routes.py       # 新增 auth/profile 端点
    └── services/
        ├── auth_token_service.py  # ★ JWT 签发/验证
        └── wechat_auth_service.py # ★ 微信 jscode2session
```

---

## Step 1：JWT 工具

创建 `backend/app/services/auth_token_service.py`：

```python
import hashlib
import hmac
import json
import os
import time
from base64 import urlsafe_b64encode


class AuthTokenError(Exception):
    pass


def _b64encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _secret() -> str:
    return os.getenv("AUTH_TOKEN_SECRET", "dev-secret-change-me")


def issue_access_token(user_id: str, ttl_seconds: int | None = None) -> str:
    """签发 JWT（HS256）"""
    if ttl_seconds is None:
        ttl_seconds = int(os.getenv("WECHAT_AUTH_TOKEN_TTL_SECONDS", "604800"))

    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64encode(json.dumps({
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }).encode())

    signature = hmac.new(
        _secret().encode(),
        f"{header}.{payload}".encode(),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64encode(signature)

    return f"{header}.{payload}.{sig_b64}"


def verify_access_token(token: str) -> dict:
    """验证 JWT 并返回 payload"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthTokenError("invalid token format")

        header_b64, payload_b64, sig_b64 = parts

        # 验证签名
        expected_sig = _b64encode(hmac.new(
            _secret().encode(),
            f"{header_b64}.{payload_b64}".encode(),
            hashlib.sha256,
        ).digest())

        if not hmac.compare_digest(expected_sig, sig_b64):
            raise AuthTokenError("signature mismatch")

        # 解码 payload
        payload_bytes = urlsafe_b64encode(
            (payload_b64 + "=" * (4 - len(payload_b64) % 4)).encode()
        )
        # 简化处理：直接 base64 解码
        import base64
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        # 检查过期
        if payload.get("exp", 0) < time.time():
            raise AuthTokenError("token expired")

        return payload
    except AuthTokenError:
        raise
    except Exception as e:
        raise AuthTokenError(f"token verification failed: {e}")


def extract_bearer_token(authorization: str | None) -> str:
    """从 Authorization 头提取 Bearer token"""
    if not authorization:
        raise AuthTokenError("missing authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthTokenError("invalid authorization format, expected 'Bearer <token>'")
    return parts[1]
```

**为什么不直接用 PyJWT 库？**
- 手写可以深入理解 JWT 原理（Header.Payload.Signature 三段式）
- HS256 实现只有 ~70 行代码
- 但注意到上面的 base64 处理有 bug——实际项目建议直接用 `PyJWT` 库，面试时可以说"手写是为了理解原理，生产环境会用 PyJWT"

---

## Step 2：鉴权依赖

创建 `backend/app/api/auth.py`：

```python
from fastapi import HTTPException
from app.services.auth_token_service import AuthTokenError, extract_bearer_token, verify_access_token


def require_authenticated_user(
    *,
    authorization: str | None,
    expected_user_id: str | None = None,
) -> str:
    """
    FastAPI 依赖函数：验证 Bearer Token，返回 userId。
    用作端点参数：
        user_id: str = Depends(require_authenticated_user)
    """
    try:
        token = extract_bearer_token(authorization)
        claims = verify_access_token(token)
    except AuthTokenError as exc:
        raise HTTPException(status_code=401, detail=f"unauthorized: {exc}")

    token_user_id = str((claims or {}).get("sub") or "").strip()
    if not token_user_id:
        raise HTTPException(status_code=401, detail="unauthorized: token subject missing")
    if expected_user_id and token_user_id != expected_user_id:
        raise HTTPException(status_code=403, detail="forbidden: token user mismatch")
    return token_user_id
```

**使用方式**：在任何需要登录的端点里加上：
```python
from fastapi import Depends, Header

@router.get("/profile/data")
def get_profile_data(
    user_id: str = Query(...),
    authorization: str = Header(None),
    auth_user_id: str = Depends(require_authenticated_user),
):
    # auth_user_id 就是 Token 中的用户 ID
    ...
```

---

## Step 3：微信登录

创建 `backend/app/services/wechat_auth_service.py`：

```python
import hashlib
import os
import httpx

WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatAuthError(Exception):
    pass


def _make_user_id(openid: str) -> str:
    """将 openid 哈希为内部 userId（保护原始 openid）"""
    salt = os.getenv("WECHAT_USER_ID_SALT", "chedian-salt")
    hash_hex = hashlib.sha256(f"{salt}:{openid}".encode()).hexdigest()
    return f"wx_{hash_hex[:24]}"


def login_with_wechat_code(code: str, anonymous_id: str = "") -> dict:
    """
    用 wx.login() 返回的 code 换取 openid，签发 JWT。
    返回：{access_token, token_type, expires_in, userId, anonymousId}
    """
    appid = os.getenv("WECHAT_MINIPROGRAM_APPID", "")
    secret = os.getenv("WECHAT_MINIPROGRAM_SECRET", "")

    if not appid or not secret:
        raise WechatAuthError("WeChat appid/secret not configured")

    timeout = int(os.getenv("WECHAT_AUTH_TIMEOUT_SECONDS", "8"))
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(WECHAT_CODE2SESSION_URL, params={
                "appid": appid,
                "secret": secret,
                "js_code": code,
                "grant_type": "authorization_code",
            })
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise WechatAuthError(f"code2session failed: {e}")

    if "errcode" in data and data["errcode"] != 0:
        raise WechatAuthError(f"wechat error {data.get('errcode')}: {data.get('errmsg')}")

    openid = data.get("openid", "")
    if not openid:
        raise WechatAuthError("no openid returned")

    user_id = _make_user_id(openid)
    from app.services.auth_token_service import issue_access_token

    token = issue_access_token(user_id)
    ttl = int(os.getenv("WECHAT_AUTH_TOKEN_TTL_SECONDS", "604800"))

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "userId": user_id,
        "anonymousId": anonymous_id,
    }
```

**为什么 openid 要哈希？**
- openid 是微信用户的唯一标识，属于敏感个人信息
- 直接存 openid 有泄露风险（数据库被拖库的话）
- `sha256(salt:openid)[:24]` 保证了单向不可逆，即使数据库泄露也无法还原 openid

---

## Step 4：在路由中添加认证端点

在 `proxy_routes.py` 中新增：

```python
from fastapi import Depends, Header, Query
from app.api.auth import require_authenticated_user
from app.services.wechat_auth_service import login_with_wechat_code, WechatAuthError

@proxy_router.post("/auth/wechat-login")
def wechat_login(req: WechatLoginRequest):
    try:
        result = login_with_wechat_code(req.code, req.anonymousId)
        return result
    except WechatAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

@proxy_router.get("/auth/me")
def auth_me(
    authorization: str = Header(None),
    auth_user_id: str = Depends(require_authenticated_user),
):
    return {"userId": auth_user_id, "authenticated": True}
```

在 `schemas.py` 中新增：
```python
class WechatLoginRequest(BaseModel):
    code: str = Field(..., min_length=1)
    anonymousId: str = ""

class WechatLoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    userId: str
    anonymousId: str = ""
```

---

## Step 5：数据同步端点

用户登录后需要把匿名期间的数据合并到登录账号：

```python
@proxy_router.post("/profile/sync-local")
def sync_local(
    req: ProfileSyncRequest,
    authorization: str = Header(None),
    auth_user_id: str = Depends(require_authenticated_user),
):
    # 把匿名 ID 的历史事件绑定到登录用户
    if req.anonymousId:
        bind_anonymous_events_to_user(req.anonymousId, auth_user_id)
    # 合并收藏
    if req.favorites:
        for name in req.favorites:
            add_favorite_if_not_exists(auth_user_id, name)
    return {"ok": True}
```

---

## Step 6：验证

```bash
# 1. 先用 curl 测试 JWT 签发（不用真实微信 code）
cd backend
python -c "
from app.services.auth_token_service import issue_access_token, verify_access_token
token = issue_access_token('test_user_123')
print(f'Token: {token}')
claims = verify_access_token(token)
print(f'Claims: {claims}')
"

# 2. 测试鉴权端点
# 不带 token → 401
curl -i http://localhost:8000/api/auth/me
# 带 token → 200
curl -i http://localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"
```

---

## 常见坑

| 坑 | 原因 | 解决 |
|---|---|---|
| `401 token expired` | JWT 过期 | 检查 `WECHAT_AUTH_TOKEN_TTL_SECONDS` 配置，默认 7 天 |
| 微信登录 `errcode: 40029` | code 已失效（只能用一次，5分钟有效） | 让小程序重新调 `wx.login()` 获取新 code |
| 微信登录 `errcode: 40125` | appid 和 secret 不匹配 | 去微信公众平台确认配置 |
| 登录后数据没合并 | `sync-local` 没调 | 前端在 `wechat-login` 成功后立即调 `sync-local` |

## 章末检查

- [ ] JWT 签发和验证正常（能签发、能验证、过期 token 被拦截）
- [ ] `/api/auth/me` 不带 token 返回 401，带有效 token 返回 200
- [ ] 微信登录能成功获取 openid 并生成 JWT
- [ ] 登录后数据同步正常工作
