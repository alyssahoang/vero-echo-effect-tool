"""
Basic password hashing utilities for the Streamlit app.

We use PBKDF2 with SHA-256 so we do not need any external dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final


ALGORITHM: Final[str] = "pbkdf2_sha256"
ITERATIONS: Final[int] = 120_000
SALT_BYTES: Final[int] = 16


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    password_bytes = password.encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", password_bytes, salt, iterations)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password must be a non-empty string.")

    salt = secrets.token_bytes(SALT_BYTES)
    digest = _pbkdf2(password, salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    if not encoded or "$" not in encoded:
        return False

    try:
        algorithm, iterations_str, salt_hex, digest_hex = encoded.split("$")
    except ValueError:
        return False

    if algorithm != ALGORITHM:
        return False

    try:
        iterations = int(iterations_str)
    except ValueError:
        return False

    try:
        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)
    except ValueError:
        return False

    candidate = _pbkdf2(password, salt, iterations)
    return hmac.compare_digest(candidate, expected_digest)
