"""微信小程序 jscode2session → hashed userId → JWT"""
import hashlib
import os
import httpx

WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatAuthError(Exception):
    """微信认证相关错误"""
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
