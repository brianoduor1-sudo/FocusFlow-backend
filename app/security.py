from cryptography.fernet import Fernet
from app.config import settings

# Generate a key once via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
_fernet = Fernet(settings.FERNET_KEY.encode())


def encrypt_token(plain_token: str) -> str:
    return _fernet.encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    return _fernet.decrypt(encrypted_token.encode()).decode()
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt

import uuid

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "nbf": now,
        "jti": str(uuid.uuid4()),
        "type": "access",
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_access_token(token: str):
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None

from werkzeug.security import check_password_hash, generate_password_hash

def hash_password(password: str) -> str:
    return generate_password_hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)
