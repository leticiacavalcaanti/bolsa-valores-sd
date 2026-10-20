"""auth-service: cadastro, login e verificação de sessão (JWT)."""
import hmac
import os
import secrets

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg2.errors import UniqueViolation
from pydantic import BaseModel, Field

from . import security
from .db import transaction

app = FastAPI(title="auth-service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
bearer = HTTPBearer()

NPC_PREFIX = "npc_"
INTERNAL_KEY = os.environ["INTERNAL_KEY"]


class NpcRequest(BaseModel):
    username: str = Field(pattern=r"^npc_[A-Za-z0-9_]{2,16}$")


class Credentials(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,20}$")
    password: str = Field(min_length=6, max_length=64)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register", status_code=201)
def register(body: Credentials):
    if body.username.lower().startswith(NPC_PREFIX):
        raise HTTPException(403, "Prefixo de nome reservado para agentes automatizados")
    try:
        with transaction() as cur:
            cur.execute(
                "INSERT INTO auth.users (username, password_hash) VALUES (%s, %s) RETURNING id",
                (body.username, security.hash_password(body.password)),
            )
            user_id = cur.fetchone()["id"]
    except UniqueViolation:
        raise HTTPException(409, "Nome de usuário já existe")
    return {"id": user_id, "username": body.username}


@app.post("/login")
def login(body: Credentials):
    with transaction() as cur:
        cur.execute("SELECT id, password_hash FROM auth.users WHERE username = %s", (body.username,))
        user = cur.fetchone()
    # Mesma mensagem para usuário inexistente e senha errada (evita enumeração de usuários).
    if not user or not security.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Usuário ou senha inválidos")
    return {
        "access_token": security.create_token(user["id"], body.username),
        "token_type": "bearer",
        "user": {"id": user["id"], "username": body.username},
    }


@app.post("/internal/npc-session")
def npc_session(body: NpcRequest, x_internal_key: str = Header(default="")):
    """Sessão para agentes automatizados. Protegida por chave interna (não exposta aos jogadores)."""
    if not hmac.compare_digest(x_internal_key, INTERNAL_KEY):
        raise HTTPException(403, "Chave interna inválida")
    with transaction() as cur:
        # Senha aleatória: o agente nunca faz login pelo fluxo público.
        cur.execute(
            "INSERT INTO auth.users (username, password_hash) VALUES (%s, %s) "
            "ON CONFLICT (username) DO UPDATE SET username = EXCLUDED.username RETURNING id",
            (body.username, security.hash_password(secrets.token_urlsafe(16))),
        )
        user_id = cur.fetchone()["id"]
    return {"access_token": security.create_token(user_id, body.username), "user": {"id": user_id}}


@app.get("/me")
def me(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        claims = security.decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, "Token inválido ou expirado")
    return {"id": int(claims["sub"]), "username": claims["username"]}
