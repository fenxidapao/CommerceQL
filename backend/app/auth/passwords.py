"""本地账号密码散列（Phase B B3）—— scrypt（n=2^14, r=8, p=1）。

层号：L1｜归属窗口：Phase B B3。

- 每用户 16B 随机盐；编码 `scrypt$n$r$p$<salt_b64>$<hash_b64>`，
  参数随行存储 ⇒ 将来调参不会让旧密码失效。
- 校验用 `hmac.compare_digest`（常数时间）；任何解析失败一律返回 `False`，
  **不抛异常** —— 数据库里的坏行不应变成 500，也不应泄露"这一行坏了"。
- 明文密码不落日志、不进异常文本。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

__all__ = ["MAX_PASSWORD_LEN", "hash_password", "verify_password"]

MAX_PASSWORD_LEN = 128
_SALT_BYTES = 16
_KEY_LEN = 64
_N = 2**14
_R = 8
_P = 1


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def hash_password(password: str) -> str:
    """返回自描述散列串。空密码/超长密码直接拒绝（DTO 已先挡一层）。"""
    if not password:
        raise ValueError("密码不得为空")
    if len(password) > MAX_PASSWORD_LEN:
        raise ValueError(f"密码超长（>{MAX_PASSWORD_LEN}）")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_LEN
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """常数时间校验；格式不认识/参数越界/解码失败 → `False`。"""
    if not password or not encoded:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_s, hash_s = encoded.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        # 防止被篡改的库行把进程拖进超长计算。
        if not (2**12 <= n <= 2**16 and 1 <= r <= 16 and 1 <= p <= 4):
            return False
        salt = _unb64(salt_s)
        expected = _unb64(hash_s)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
