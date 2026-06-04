"""第 11 章测试：多端账号体系 —— 密码哈希 + 邮箱注册/登录"""
import time
import pytest
import sqlite3
from fastapi.testclient import TestClient

from app.main import app
from app.services.password_service import hash_password, verify_password

client = TestClient(app)

# 用时间戳确保每次测试 run 的邮箱唯一（避免 SQLite 持久化残留冲突）
_TS = str(int(time.time() * 1000))[-8:]


def _em(label: str) -> str:
    return f"ch11_{label}_{_TS}@test.com"


# ---- 密码服务 ----

class TestPasswordService:
    def test_hash_and_verify_round_trip(self):
        pw = "mySecureP@ss1"
        stored = hash_password(pw)
        assert stored.startswith("pbkdf2_sha256$")
        assert verify_password(pw, stored) is True

    def test_wrong_password_rejected(self):
        stored = hash_password("correct")
        assert verify_password("wrong", stored) is False

    def test_different_salts_yield_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2
        # 两个都能验证
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True

    def test_bad_stored_format(self):
        assert verify_password("anything", "not_a_valid_hash") is False

    def test_empty_password(self):
        stored = hash_password("")
        assert verify_password("", stored) is True
        assert verify_password("x", stored) is False


# ---- 邮箱注册 ----

class TestEmailRegister:
    def test_register_success(self):
        r = client.post("/api/auth/email-register", json={
            "email": _em("reg_ok"),
            "password": "123456",
            "anonymousId": "anon_test",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["access_token"]
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] > 0
        assert data["userId"].startswith("em_")
        assert data["anonymousId"] == "anon_test"

    def test_duplicate_email_409(self):
        client.post("/api/auth/email-register", json={
            "email": _em("dup"), "password": "123456",
        })
        r = client.post("/api/auth/email-register", json={
            "email": _em("dup"), "password": "654321",
        })
        assert r.status_code == 409

    def test_short_password_422(self):
        r = client.post("/api/auth/email-register", json={
            "email": _em("short"), "password": "12345",
        })
        assert r.status_code == 422

    def test_invalid_email_422(self):
        r = client.post("/api/auth/email-register", json={
            "email": "not-an-email", "password": "123456",
        })
        assert r.status_code == 422

    def test_register_initializes_schema_on_clean_database(self, tmp_path, monkeypatch):
        import app.services.account_service as account_service
        import app.services.shop_repository as shop_repository

        db_path = str(tmp_path / "clean_chapter11.db")
        monkeypatch.setattr(account_service, "DB_PATH", db_path)
        monkeypatch.setattr(shop_repository, "DB_PATH", db_path)
        monkeypatch.setattr(shop_repository, "_db_ready", False)

        r = client.post("/api/auth/email-register", json={
            "email": f"clean_{_TS}@test.com",
            "password": "123456",
        })
        assert r.status_code == 200

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT email FROM users WHERE email = ?",
                (f"clean_{_TS}@test.com",),
            ).fetchone()
            assert row is not None
        finally:
            conn.close()


# ---- 邮箱登录 ----

class TestEmailLogin:
    def test_login_success(self):
        client.post("/api/auth/email-register", json={
            "email": _em("login"), "password": "mypassword",
        })
        r = client.post("/api/auth/email-login", json={
            "email": _em("login"), "password": "mypassword",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["userId"].startswith("em_")
        assert data["access_token"]

    def test_wrong_password_401(self):
        client.post("/api/auth/email-register", json={
            "email": _em("wrongpw"), "password": "correct",
        })
        r = client.post("/api/auth/email-login", json={
            "email": _em("wrongpw"), "password": "wrong",
        })
        assert r.status_code == 401

    def test_nonexistent_user_401(self):
        r = client.post("/api/auth/email-login", json={
            "email": _em("nobody"), "password": "whatever",
        })
        assert r.status_code == 401

    def test_empty_fields_422(self):
        r = client.post("/api/auth/email-login", json={})
        assert r.status_code == 422

    def test_email_login_binds_anonymous_events(self):
        from app.services.usage_events import DB_PATH, log_usage_event

        email = _em("bind_anon")
        anon = f"anon_bind_{_TS}"
        log_usage_event(
            event_type="query",
            anonymous_id=anon,
            query_text="今天想吃清淡一点",
        )
        client.post("/api/auth/email-register", json={
            "email": email,
            "password": "mypassword",
        })
        r = client.post("/api/auth/email-login", json={
            "email": email,
            "password": "mypassword",
            "anonymousId": anon,
        })
        assert r.status_code == 200
        user_id = r.json()["userId"]

        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                "SELECT user_id FROM usage_events WHERE anonymous_id = ? ORDER BY id DESC LIMIT 1",
                (anon,),
            ).fetchone()
            assert row is not None
            assert row[0] == user_id
        finally:
            conn.close()


# ---- 邮箱登录后访问受保护接口 ----

class TestAuthWithEmailToken:
    def test_access_protected_endpoint_with_email_token(self):
        r = client.post("/api/auth/email-register", json={
            "email": _em("protected"), "password": "123456",
        })
        token = r.json()["access_token"]

        r2 = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert r2.status_code == 200
        assert r2.json()["authenticated"] is True

    def test_collect_favorite_with_email_token(self):
        r = client.post("/api/auth/email-register", json={
            "email": _em("favuser"), "password": "123456",
        })
        token = r.json()["access_token"]

        r2 = client.post("/api/v1/favorites", json={
            "shop_id": 1, "shop_name": "学子餐厅",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

        r3 = client.get("/api/v1/favorites", headers={
            "Authorization": f"Bearer {token}",
        })
        assert r3.status_code == 200
        assert len(r3.json()["favorites"]) >= 1
