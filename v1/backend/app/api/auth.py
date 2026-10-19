"""FastAPI 鉴权依赖 —— Bearer Token 验证"""
from fastapi import Header, HTTPException

from app.services.auth_token_service import (
    AuthTokenError,
    extract_bearer_token,
    verify_access_token,
)


def require_authenticated_user(
    authorization: str | None = Header(None),
) -> str:
    """
    FastAPI 依赖函数：验证 Bearer Token，返回 userId。

    用法：
        @router.get("/protected")
        def protected_endpoint(user_id: str = Depends(require_authenticated_user)):
            ...
    """
    try:
        token = extract_bearer_token(authorization)
        claims = verify_access_token(token)
    except AuthTokenError as exc:
        raise HTTPException(status_code=401, detail=f"unauthorized: {exc}")

    user_id = str((claims or {}).get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthorized: token subject missing")
    return user_id
