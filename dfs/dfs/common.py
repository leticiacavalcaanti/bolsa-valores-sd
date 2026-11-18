"""Utilitários comuns: configuração por variáveis de ambiente e log estruturado (JSON, uma linha por evento)."""
import hashlib
import json
import os
import sys
import time


def env(name, default, cast=str):
    return cast(os.environ.get(name, default))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def log(component: str, event: str, **fields):
    """RF12: data/hora, componente, evento e identificador do arquivo/bloco (quando houver)."""
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z",
           "component": component, "event": event, **fields}
    print(json.dumps(rec, default=str), file=sys.stdout, flush=True)
