"""B3：scrypt 密码散列（零 I/O）。"""

from __future__ import annotations

import pytest

from app.auth.passwords import MAX_PASSWORD_LEN, hash_password, verify_password


def test_hash_roundtrip_and_salt_is_random() -> None:
    first = hash_password("correct-horse-battery")
    second = hash_password("correct-horse-battery")
    assert first != second  # 每次新盐
    assert first.startswith("scrypt$16384$8$1$")
    assert verify_password("correct-horse-battery", first)
    assert verify_password("correct-horse-battery", second)


def test_wrong_password_is_rejected() -> None:
    encoded = hash_password("correct-horse-battery")
    assert not verify_password("wrong-password", encoded)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "plaintext",
        "scrypt$16384$8$1$not-base64$also-bad",
        "argon2$16384$8$1$AAAA$AAAA",
        "scrypt$999999$8$1$AAAA$AAAA",  # 参数越界不得进入计算
    ],
)
def test_malformed_hash_returns_false_without_raising(bad: str) -> None:
    assert not verify_password("whatever", bad)


def test_empty_and_overlong_passwords_are_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("")
    with pytest.raises(ValueError):
        hash_password("x" * (MAX_PASSWORD_LEN + 1))
