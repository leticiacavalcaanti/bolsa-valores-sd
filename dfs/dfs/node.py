"""Nó de armazenamento: um disco (diretório de dados). Armazena e serve blocos, verifica hashes,
envia heartbeats com espaço usado/total, copia blocos de outros nós quando o controlador pedir
e faz scrubbing periódico em segundo plano.

Registro ativo (RF6): o nó se registra sozinho no controlador (endereço por variável de ambiente), sem reiniciar
nada nem editar configuração central. Se o controlador reiniciar (heartbeat devolve 404), o nó se registra de novo.
"""
import os
import threading
import time

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from .common import env, log, sha256_hex

NODE_ID = env("NODE_ID", "node1")
MACHINE = env("MACHINE", NODE_ID)           # máquina física simulada (vários discos podem compartilhar a máquina)
DISK = env("DISK", "d1")
PUBLIC_URL = env("PUBLIC_URL", f"http://{NODE_ID}:8000")
CONTROLLER = env("CONTROLLER_URL", "http://controller:9000")
DATA_DIR = env("DATA_DIR", "/data")
CAPACITY_MB = env("CAPACITY_MB", 0, float)  # capacidade simulada do disco (0 = usa o disco real)
HEARTBEAT_S = env("HEARTBEAT_INTERVAL_S", 2, float)
SCRUB_S = env("SCRUB_INTERVAL_S", 30, float)
REPL_MBPS = env("REPLICATION_MBPS", 0, float)  # limite de banda ao copiar blocos (0 = sem limite)
C = NODE_ID

os.makedirs(DATA_DIR, exist_ok=True)
app = FastAPI(title=f"dfs-node-{NODE_ID}")
io_lock = threading.Lock()


def path_of(chunk_id):
    if "/" in chunk_id or ".." in chunk_id:
        raise HTTPException(400, "id de bloco inválido")
    return os.path.join(DATA_DIR, chunk_id)


def chunk_ids():
    return [f for f in os.listdir(DATA_DIR) if not f.endswith((".sha", ".tmp"))]


def usage():
    used = sum(os.path.getsize(path_of(c)) for c in chunk_ids() if os.path.exists(path_of(c)))
    if CAPACITY_MB:
        return used, int(CAPACITY_MB * 1024 * 1024)
    import shutil
    d = shutil.disk_usage(DATA_DIR)
    return used, d.total


def store(chunk_id, data: bytes, expected_sha: str):
    """Grava o bloco só se o hash conferir (RF4a) e de forma atômica: escreve .tmp e renomeia."""
    got = sha256_hex(data)
    if got != expected_sha:
        log(C, "CHUNK_REJECTED_HASH", chunk=chunk_id, expected=expected_sha[:12], got=got[:12])
        raise HTTPException(422, "hash do bloco não confere")
    p = path_of(chunk_id)
    with io_lock:
        with open(p + ".tmp", "wb") as f:
            f.write(data)
        os.replace(p + ".tmp", p)
        with open(p + ".sha", "w") as f:
            f.write(got)
    log(C, "CHUNK_STORED", chunk=chunk_id, bytes=len(data), sha256=got[:12])
    return got


@app.put("/chunks/{chunk_id}")
async def put_chunk(chunk_id: str, request: Request, x_sha256: str = Header(...)):
    data = await request.body()
    return {"ok": True, "sha256": store(chunk_id, data, x_sha256)}


@app.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str):
    p = path_of(chunk_id)
    if not os.path.exists(p):
        raise HTTPException(404, "bloco não encontrado")
    with open(p, "rb") as f:
        return Response(f.read(), media_type="application/octet-stream")


@app.delete("/chunks/{chunk_id}")
def delete_chunk(chunk_id: str):
    remove(chunk_id)
    return {"ok": True}


def remove(chunk_id):
    p = path_of(chunk_id)
    for suffix in ("", ".sha", ".tmp"):
        try:
            os.remove(p + suffix)
        except FileNotFoundError:
            pass
    log(C, "CHUNK_DELETED", chunk=chunk_id)


class Replicate(BaseModel):
    chunk_id: str
    source_url: str
    sha256: str


@app.post("/replicate")
def replicate(r: Replicate):
    """Puxa o bloco de outro nó (a pedido do controlador), verifica o hash e grava. Banda limitada se configurado."""
    t0 = time.time()
    resp = requests.get(f"{r.source_url}/chunks/{r.chunk_id}", stream=True, timeout=60)
    resp.raise_for_status()
    buf = bytearray()
    for part in resp.iter_content(256 * 1024):
        buf += part
        if REPL_MBPS:                                    # limite de banda: dorme o suficiente para respeitar o teto
            expected = len(buf) / (REPL_MBPS * 1024 * 1024)
            time.sleep(max(0.0, expected - (time.time() - t0)))
    store(r.chunk_id, bytes(buf), r.sha256)
    return {"ok": True, "bytes": len(buf)}


@app.get("/info")
def info():
    used, total = usage()
    return {"id": NODE_ID, "machine": MACHINE, "disk": DISK, "used": used, "total": total, "chunks": len(chunk_ids())}


@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------------ laços de fundo
def report_corrupt(chunk_id):
    try:
        requests.post(f"{CONTROLLER}/report-corrupt", json={"chunk_id": chunk_id, "node_id": NODE_ID}, timeout=5)
    except Exception as e:
        log(C, "REPORT_FAILED", chunk=chunk_id, error=str(e)[:80])


def scrub_once():
    """RF4c: relê cada bloco e compara com o hash gravado. Corrompido: descarta e avisa o controlador,
    que o substitui por cópia íntegra de outra réplica."""
    for cid in chunk_ids():
        try:
            with open(path_of(cid), "rb") as f:
                got = sha256_hex(f.read())
            with open(path_of(cid) + ".sha") as f:
                want = f.read().strip()
        except FileNotFoundError:
            continue
        if got != want:
            log(C, "SCRUB_CORRUPT_FOUND", chunk=cid, expected=want[:12], got=got[:12])
            remove(cid)
            report_corrupt(cid)
    log(C, "SCRUB_DONE", chunks=len(chunk_ids()))


def scrub_loop():
    while SCRUB_S > 0:
        time.sleep(SCRUB_S)
        try:
            scrub_once()
        except Exception as e:
            log(C, "SCRUB_ERROR", error=str(e)[:100])


@app.post("/scrub")
def scrub_now():
    """Dispara o scrubbing sob demanda (usado nos testes e na demonstração)."""
    scrub_once()
    return {"ok": True}


def full_report():
    """Hash real de cada bloco guardado (relatório de reconciliação ao (re)registrar)."""
    out = {}
    for cid in chunk_ids():
        try:
            with open(path_of(cid), "rb") as f:
                out[cid] = sha256_hex(f.read())
        except FileNotFoundError:
            pass
    return out


def register():
    used, total = usage()
    body = {"id": NODE_ID, "url": PUBLIC_URL, "machine": MACHINE, "disk": DISK, "total": total, "used": used,
            "chunks": full_report()}
    while True:
        try:
            r = requests.post(f"{CONTROLLER}/nodes/register", json=body, timeout=10)
            r.raise_for_status()
            for cid in r.json().get("delete", []):   # blocos obsoletos segundo os metadados
                remove(cid)
            log(C, "REGISTERED", controller=CONTROLLER, chunks=len(body["chunks"]))
            return
        except Exception as e:
            log(C, "REGISTER_RETRY", error=str(e)[:80])
            time.sleep(2)


def heartbeat_loop():
    register()
    beat = 0
    while True:
        time.sleep(HEARTBEAT_S)
        beat += 1
        used, total = usage()
        body = {"id": NODE_ID, "used": used, "total": total}
        if beat % 10 == 0:
            body["chunks"] = chunk_ids()
        try:
            r = requests.post(f"{CONTROLLER}/nodes/heartbeat", json=body, timeout=5)
            if r.status_code == 404:
                log(C, "CONTROLLER_FORGOT_ME")
                register()
                continue
            r.raise_for_status()
            for cid in r.json().get("delete", []):
                remove(cid)
        except Exception as e:
            log(C, "HEARTBEAT_FAILED", error=str(e)[:80])


@app.on_event("startup")
def start_background():
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=scrub_loop, daemon=True).start()
