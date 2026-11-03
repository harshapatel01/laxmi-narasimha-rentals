import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote

from argon2 import PasswordHasher, Type
from cryptography.fernet import Fernet

from app.core.config import get_settings

password_hasher = PasswordHasher(type=Type.ID)


def hash_token(token: str) -> str:
    return hmac.new(get_settings().auth_key, token.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(mobile: str, otp: str, salt: str) -> str:
    message = f"{mobile}:{otp}:{salt}".encode("utf-8")
    return hmac.new(get_settings().auth_key, message, hashlib.sha256).hexdigest()


def new_session_tokens() -> tuple[str, str]:
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)


def encrypt_totp_secret(secret: str) -> str:
    return Fernet(get_settings().totp_key.encode("utf-8")).encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_totp_secret(encrypted: str) -> str:
    return Fernet(get_settings().totp_key.encode("utf-8")).decrypt(encrypted.encode("ascii")).decode("utf-8")


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def verify_totp(secret: str, code: str, *, timestamp: float | None = None) -> bool:
    current_step = int((time.time() if timestamp is None else timestamp) // 30)
    normalized_secret = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(normalized_secret, casefold=True)
    for step in (current_step - 1, current_step, current_step + 1):
        digest = hmac.new(key, step.to_bytes(8, "big"), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        number = (
            ((digest[offset] & 0x7F) << 24)
            | ((digest[offset + 1] & 0xFF) << 16)
            | ((digest[offset + 2] & 0xFF) << 8)
            | (digest[offset + 3] & 0xFF)
        )
        expected = f"{number % 1_000_000:06d}"
        if hmac.compare_digest(expected, code):
            return True
    return False


def provisioning_uri(secret: str, username: str) -> str:
    label = quote(f"Laxmi Narasimha Rentals:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer=Laxmi%20Narasimha%20Rentals&digits=6&period=30"
