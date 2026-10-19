"""PBKDF2 HMAC-SHA256 密码哈希 —— 标准库实现，无额外依赖"""
import hashlib
import hmac
import os
import secrets

# 迭代次数（OWASP 推荐 >= 600_000 for SHA256，学习项目用 100_000 更快）
PBKDF2_ITERATIONS = 100_000
SALT_BYTES = 16
HASH_NAME = "sha256"


def hash_password(password: str) -> str:
    """
    PBKDF2 HMAC-SHA256 哈希密码。
    存储格式：pbkdf2_sha256$iterations$salt_hex$hash_hex
    """
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """
    验证密码。
    stored 格式：pbkdf2_sha256$iterations$salt_hex$hash_hex
    使用常量时间比较防止时序攻击。
    """
    try:
        algo, iterations_str, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(expected, actual)
    except (ValueError, AttributeError):
        return False
