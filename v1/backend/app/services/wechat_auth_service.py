"""微信小程序 jscode2session → hashed userId → JWT"""
import hashlib
import os
import httpx

WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatAuthError(Exception):
    """微信认证相关错误"""
    pass


def _make_openid_hash(openid: str) -> str:
    """对 openid 做单向哈希（保护原始 openid）"""
    salt = os.getenv("WECHAT_USER_ID_SALT", "chedian-salt")
    return hashlib.sha256(f"{salt}:{openid}".encode()).hexdigest()[:24]


def _make_user_id(openid_hash: str) -> str:
    """由 openid_hash 生成系统内部 userId"""
    return f"wx_{openid_hash}"


def login_with_wechat_code(code: str, anonymous_id: str = "") -> dict:
    """
    用 wx.login() 返回的 code 换取 openid，签发 JWT。
    同时写入 users 表和 wechat_identities 表（幂等）。
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
    except httpx.HTTPError as e:
        raise WechatAuthError(f"code2session request failed: {e}")
    except Exception as e:
        raise WechatAuthError(f"code2session failed: {e}")

    if "errcode" in data and data["errcode"] != 0:
        raise WechatAuthError(
            f"wechat error {data.get('errcode')}: {data.get('errmsg', 'unknown')}"
        )

    openid = data.get("openid", "")
    if not openid:
        raise WechatAuthError("no openid returned")

    openid_hash = _make_openid_hash(openid)
    user_id = _make_user_id(openid_hash)

    # 写入 users + wechat_identities（幂等，跨多端统一 user_id）
    try:
        from app.services.account_service import ensure_wechat_user, save_wechat_identity
        from app.services.usage_events import bind_anonymous_events_to_user

        ensure_wechat_user(user_id)
        save_wechat_identity(user_id, openid_hash)
        if anonymous_id:
            bind_anonymous_events_to_user(anonymous_id, user_id)
    except Exception as e:
        raise WechatAuthError(f"account persistence failed: {e}") from e

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
