"""Hash de senhas (bcrypt) e emissão/validação de tokens JWT."""
import os
import time

import bcrypt
import jwt

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 8 * 60 * 60


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user_id: int, username: str) -> str:
    now = int(time.time())
    claims = {"sub": str(user_id), "username": username, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Levanta jwt.PyJWTError se o token for inválido ou estiver expirado."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
