"""Account service for email users and WeChat identities."""
import os
import sqlite3
import uuid
from pathlib import Path

DB_PATH = os.getenv("SQLITE_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chedian.db"))


def _ensure_database() -> None:
    from app.services import shop_repository

    shop_repository._ensure_database()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_email_user(email: str, password_hash: str) -> str:
    """Create an email user and return user_id. Raises ValueError on duplicate email."""
    _ensure_database()
    user_id = f"em_{uuid.uuid4().hex[:16]}"
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)",
            (user_id, email.strip().lower(), password_hash),
        )
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        raise ValueError("该邮箱已注册")
    finally:
        conn.close()


def get_user_by_email(email: str) -> dict | None:
    """Fetch a user by normalized email."""
    _ensure_database()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> dict | None:
    """Fetch a user by internal user_id."""
    _ensure_database()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def ensure_wechat_user(user_id: str) -> None:
    """Ensure a WeChat user has a row in users."""
    _ensure_database()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def save_wechat_identity(user_id: str, openid_hash: str) -> None:
    """Persist the binding between a WeChat identity and an internal user."""
    _ensure_database()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO wechat_identities (user_id, openid_hash) VALUES (?, ?)",
            (user_id, openid_hash),
        )
        conn.commit()
    finally:
        conn.close()
