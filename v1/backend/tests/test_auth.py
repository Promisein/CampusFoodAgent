"""用户认证测试 —— JWT 签发/验证、auth/me 鉴权、wechat-login"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_token_service import (
    AuthTokenError,
    extract_bearer_token,
    issue_access_token,
    verify_access_token,
)

client = TestClient(app)


# ---- JWT 签发/验证 ----

class TestJwtToken:
    def test_issue_and_verify_round_trip(self):
        """签发后能成功验证，返回正确 userId"""
        token = issue_access_token("test_user_123")
        claims = verify_access_token(token)
        assert claims["sub"] == "test_user_123"
        assert "iat" in claims
        assert "exp" in claims
        assert claims["exp"] > claims["iat"]

    def test_expired_token_rejected(self, monkeypatch):
        """过期 token 被拒绝"""
        import time
        original_time = time.time
        token = issue_access_token("test_user", ttl_seconds=1)
        # 快进 2 秒让 token 过期
        monkeypatch.setattr(time, "time", lambda: original_time() + 2)
        with pytest.raises(AuthTokenError, match="expired"):
            verify_access_token(token)

    def test_tampered_payload_rejected(self):
        """篡改 payload 后签名不匹配"""
        token = issue_access_token("test_user")
        parts = token.split(".")
        # 改 payload（中间段）
        parts[1] = "dGFtcGVyZWQ"  # base64 of "tampered"
        fake_token = ".".join(parts)
        with pytest.raises(AuthTokenError, match="signature"):
            verify_access_token(fake_token)

    def test_wrong_secret_rejected(self, monkeypatch):
        """不同 secret 签的 token 无法验证"""
        token = issue_access_token("test_user")
        # 换 secret 后验证应失败
        monkeypatch.setenv("AUTH_TOKEN_SECRET", "different-secret")
        with pytest.raises(AuthTokenError, match="signature"):
            verify_access_token(token)

    def test_short_token_rejected(self):
        with pytest.raises(AuthTokenError, match="format"):
            verify_access_token("tooshort")

    def test_wrong_format_token_rejected(self):
        with pytest.raises(AuthTokenError, match="format"):
            verify_access_token("a.b.c.d")


# ---- extract_bearer_token ----

class TestExtractBearer:
    def test_extracts_valid_header(self):
        token = extract_bearer_token("Bearer abc123")
        assert token == "abc123"

    def test_missing_header_raises(self):
        with pytest.raises(AuthTokenError, match="missing"):
            extract_bearer_token(None)

    def test_missing_header_empty_raises(self):
        with pytest.raises(AuthTokenError, match="missing"):
            extract_bearer_token("")

    def test_non_bearer_prefix_raises(self):
        with pytest.raises(AuthTokenError, match="format"):
            extract_bearer_token("Basic abc123")


# ---- auth/me 端点 ----

class TestAuthMe:
    def test_no_token_returns_401(self):
        """不带 Authorization 头 → 401"""
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    def test_invalid_token_returns_401(self):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer bad.token.here"})
        assert r.status_code == 401

    def test_expired_token_returns_401(self, monkeypatch):
        import time
        original_time = time.time
        token = issue_access_token("user1", ttl_seconds=1)
        monkeypatch.setattr(time, "time", lambda: original_time() + 2)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_valid_token_returns_user_id(self):
        token = issue_access_token("user_42")
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert data["userId"] == "user_42"
        assert data["authenticated"] is True

    def test_malformed_auth_header_401(self):
        r = client.get("/api/auth/me", headers={"Authorization": "NoBearer token"})
        assert r.status_code == 401


# ---- wechat-login 端点 ----

class TestWechatLogin:
    def test_missing_code_422(self):
        r = client.post("/api/auth/wechat-login", json={})
        assert r.status_code == 422

    def test_empty_code_422(self):
        r = client.post("/api/auth/wechat-login", json={"code": ""})
        assert r.status_code == 422

    def test_no_appid_configured_400(self):
        """未配置 appid/secret 时返回 400"""
        r = client.post("/api/auth/wechat-login", json={"code": "fake_wechat_code"})
        assert r.status_code == 400
        assert "not configured" in r.json()["detail"].lower()


# ---- sync-local 端点 ----

class TestSyncLocal:
    def test_requires_auth(self):
        """不带 token 调 sync-local → 401"""
        r = client.post("/api/profile/sync-local", json={})
        assert r.status_code == 401

    def test_sync_ok_with_valid_token(self):
        token = issue_access_token("user_1")
        r = client.post(
            "/api/profile/sync-local",
            json={"anonymousId": "anon_old", "favorites": ["学子餐厅"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
