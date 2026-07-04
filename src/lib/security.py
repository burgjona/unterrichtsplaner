"""Sicherheits-Primitive: Passwort-Hashing (argon2id), Token, API-Key-Verschlüsselung.

Der nutzereigene Anthropic-API-Key wird mit AES-256-GCM verschlüsselt; der
Master-Key kommt als base64-kodierte 32 Byte aus ENV APP_SECRET_KEY – niemals
im Repo, niemals im Klartext in der DB.
"""
from __future__ import annotations

import base64
import os
import secrets
from typing import Tuple

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings

_ph = PasswordHasher()  # argon2id mit sinnvollen Defaults


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _ph.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def secret_available() -> bool:
    return bool(settings.app_secret_key)


def _aesgcm() -> AESGCM:
    if not settings.app_secret_key:
        raise RuntimeError("APP_SECRET_KEY ist nicht gesetzt.")
    key = base64.b64decode(settings.app_secret_key)
    if len(key) != 32:
        raise RuntimeError("APP_SECRET_KEY muss 32 Byte (base64-kodiert) lang sein.")
    return AESGCM(key)


def encrypt_secret(plaintext: str) -> Tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ciphertext = _aesgcm().encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def decrypt_secret(ciphertext: bytes, nonce: bytes) -> str:
    return _aesgcm().decrypt(nonce, ciphertext, None).decode("utf-8")
