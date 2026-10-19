"""手写 JWT HS256 —— 理解 Header.Payload.Signature 三段式结构"""
import base64
import hashlib
import hmac
import json
import os
import time


class AuthTokenError(Exception):
    """JWT 相关错误"""
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    # 补齐被去掉的 = 填充
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _secret() -> str:
    return os.getenv("AUTH_TOKEN_SECRET", "dev-secret-change-me")


def issue_access_token(user_id: str, ttl_seconds: int | None = None) -> str:
    """签发 JWT（HS256）"""
    if ttl_seconds is None:
        ttl_seconds = int(os.getenv("WECHAT_AUTH_TOKEN_TTL_SECONDS", "604800"))

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64url_encode(json.dumps({
        "sub": user_id,
        "iat": now,
        "exp": now + ttl_seconds,
    }).encode())

    message = f"{header}.{payload}"
    signature = hmac.new(
        _secret().encode(),
        message.encode(),
        hashlib.sha256,
    ).digest()

    return f"{message}.{_b64url_encode(signature)}"


def verify_access_token(token: str) -> dict:
    """验证 JWT 并返回 payload。验证失败抛出 AuthTokenError"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthTokenError("invalid token format")

        header_b64, payload_b64, sig_b64 = parts

        # 验证签名
        expected_sig = _b64url_encode(hmac.new(
            _secret().encode(),
            f"{header_b64}.{payload_b64}".encode(),
            hashlib.sha256,
        ).digest())

        if not hmac.compare_digest(expected_sig, sig_b64):
            raise AuthTokenError("signature mismatch")

        # 解码 payload
        payload = json.loads(_b64url_decode(payload_b64))

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
