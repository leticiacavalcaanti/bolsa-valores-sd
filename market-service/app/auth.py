"""Validação do JWT emitido pelo auth-service (segredo compartilhado)."""
import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

JWT_SECRET = os.environ["JWT_SECRET"]
bearer = HTTPBearer()


class User:
    def __init__(self, user_id: int, username: str):
        self.id = user_id
        self.username = username


def user_from_token(token: str) -> User:
    """Levanta jwt.PyJWTError se o token for inválido ou estiver expirado."""
    claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    return User(int(claims["sub"]), claims["username"])


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> User:
    try:
        return user_from_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, "Token inválido ou expirado")
