import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings

JWT_ALGORITHM = "HS256"
PASSWORD_RULE = "8 caractères minimum dont une majuscule, une minuscule et un chiffre"
_PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(4)).decode()


def validate_password_strength(password: str) -> str:
    if not _PASSWORD_RE.match(password):
        raise ValueError(f"Mot de passe trop faible : {PASSWORD_RULE}")
    if len(password.encode()) > 72:
        raise ValueError("Mot de passe trop long (72 octets maximum)")
    return password


def hash_password(password: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        bcrypt.checkpw(password.encode(), _DUMMY_HASH.encode())
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int, email: str, role: str) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.jwt_expires_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM), expires_in


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub"]},
    )
