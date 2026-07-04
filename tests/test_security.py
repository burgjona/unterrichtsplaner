from src.lib.security import (
    decrypt_secret, encrypt_secret, generate_token, hash_password, verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("Geheim1234!")
    assert h != "Geheim1234!" and h.startswith("$argon2id$")
    assert verify_password(h, "Geheim1234!") is True
    assert verify_password(h, "falsch") is False


def test_verify_rejects_garbage_hash():
    assert verify_password("kein-gueltiger-hash", "x") is False


def test_token_is_random_and_urlsafe():
    a, b = generate_token(), generate_token()
    assert a != b and len(a) >= 32


def test_api_key_encryption_roundtrip():
    # APP_SECRET_KEY wird in conftest gesetzt.
    secret = "sk-ant-api03-EXAMPLE-1234"
    cipher, nonce = encrypt_secret(secret)
    assert isinstance(cipher, bytes) and secret.encode() not in cipher  # kein Klartext
    assert decrypt_secret(cipher, nonce) == secret
