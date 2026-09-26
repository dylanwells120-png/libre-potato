"""Scrypt password hashes. The plaintext password is never stored."""

from __future__ import annotations

import base64
import hashlib
import hmac

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024


class PasswordHashError(ValueError):
    pass


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordHashError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordHashError("That password is too long.")
    salt = _fresh_salt()
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return _format(SCRYPT_N, SCRYPT_R, SCRYPT_P, salt, derived)


def verify_password(password: str, stored: str) -> bool:
    if not isinstance(password, str) or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        n, r, p, salt, expected = parse_password_hash(stored)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (PasswordHashError, ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, expected)


def parse_password_hash(stored: str) -> tuple[int, int, int, bytes, bytes]:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        raise PasswordHashError("Password hash must look like scrypt$n$r$p$salt$hash.")
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.urlsafe_b64decode(parts[4])
        expected = base64.urlsafe_b64decode(parts[5])
    except (ValueError, TypeError) as exc:
        raise PasswordHashError("Password hash is not valid base64.") from exc
    if n < 2**14 or n > 2**20 or n & (n - 1) != 0:
        raise PasswordHashError("Password hash uses an unsupported scrypt cost.")
    if not 1 <= r <= 16 or not 1 <= p <= 4:
        raise PasswordHashError("Password hash uses unsupported scrypt parameters.")
    if len(salt) < 16 or len(expected) < 16:
        raise PasswordHashError("Password hash is incomplete.")
    return n, r, p, salt, expected


def equal_text(left: str, right: str) -> bool:
    """Compare two strings without leaking which one matched via a short-circuit."""
    return hmac.compare_digest(
        hashlib.sha256(left.encode("utf-8")).digest(),
        hashlib.sha256(right.encode("utf-8")).digest(),
    )


def _fresh_salt() -> bytes:
    import secrets

    return secrets.token_bytes(16)


def _format(n: int, r: int, p: int, salt: bytes, derived: bytes) -> str:
    return "scrypt${}${}${}${}${}".format(
        n,
        r,
        p,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )
