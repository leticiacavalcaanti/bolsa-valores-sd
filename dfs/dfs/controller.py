"""Controlador + nó de metadados (um único processo acumula os dois papéis).

Plano de controle apenas: o conteúdo dos arquivos NUNCA passa por aqui (vai do cliente direto aos nós).
- Metadados (árvore de diretórios, arquivo -> blocos -> réplicas) persistidos em SQLite (RF10).
- Heartbeats e timeouts: vivo -> suspeito -> morto (RF5). Nós se registram sozinhos (RF6).
- Posicionamento: nós vivos, abaixo do limite de uso, nunca repetindo disco (nó) e, havendo máquinas
  suficientes, nunca repetindo máquina; entre os candidatos, o de mais espaço livre (RF3, RF7).
- Re-replicação automática com prioridade para blocos com menos réplicas vivas e limite de concorrência.
- Concorrência (RF8): escrita em duas fases (allocate -> commit). O arquivo só fica visível no commit,
  que troca a versão numa única transação: leitores veem a versão antiga inteira ou a nova inteira.
  Duas escritas no mesmo caminho: vale o último commit (last-writer-wins).
"""
import os
import posixpath
import random
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .common import env, log

C = "controller"
REPLICATION = env("REPLICATION", 3, int)           # N padrão
WRITE_QUORUM = env("WRITE_QUORUM", 2, int)         # W: réplicas confirmadas antes de responder ao cliente
CHUNK_MB = env("CHUNK_MB", 4, float)
HB_SUSPECT = env("HEARTBEAT_SUSPECT_S", 6, float)
HB_DEAD = env("HEARTBEAT_DEAD_S", 12, float)
DISK_LIMIT = env("DISK_LIMIT", 0.9, float)
MAX_REREPL = env("MAX_REREPL", 4, int)             # cópias simultâneas de re-replicação
ALLOW_UNDER = env("ALLOW_UNDER_REPLICATED", "true").lower() == "true"  # política: aceitar sub-replicada?
DB_PATH = env("DB_PATH", "/data/meta.db")

app = FastAPI(title="dfs-controller")
lock = threading.RLock()
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)  # autocommit; BEGIN/COMMIT explícitos
db.row_factory = sqlite3.Row
db.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS dirs (path TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, version TEXT, size INT, sha256 TEXT, mtime REAL, replicas INT);
CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, path TEXT, idx INT, size INT, sha256 TEXT);
CREATE TABLE IF NOT EXISTS replicas (chunk_id TEXT, node_id TEXT, PRIMARY KEY (chunk_id, node_id));
INSERT OR IGNORE INTO dirs VALUES ('/');
""")

nodes: dict[str, dict] = {}        # estado volátil: os nós se registram de novo após reinício do controlador
pending: dict[str, dict] = {}      # escritas alocadas e ainda não confirmadas
inflight: dict[str, dict] = {}     # re-replicações em andamento: chunk_id -> info
garbage: dict[str, set] = {}       # node_id -> blocos a apagar (arquivos removidos/substituídos)
stats = {"bytes_copied": 0, "copies_done": 0, "copies_failed": 0, "recovery_s": [], "corrupt_reports": 0,
         "files_put": 0, "degraded_since": None, "min_live_replicas": None, "node_dead_events": []}
pool = ThreadPoolExecutor(MAX_REREPL)


# ------------------------------------------------------------------ utilidades
def norm(path: str) -> str:
    # lstrip: normpath preserva "//" no início (regra POSIX), o que quebraria a árvore de diretórios
    return posixpath.normpath("/" + path.strip().lstrip("/"))


def node_status(n) -> str:
    age = time.time() - n["last_hb"]
    return "alive" if age <= HB_SUSPECT else ("suspect" if age <= HB_DEAD else "dead")


def live_nodes(include_suspect=True):
    ok = ("alive", "suspect") if include_suspect else ("alive",)
    return {i: n for i, n in nodes.items() if node_status(n) in ok}


def chunk_live_replicas(chunk_id):
    rows = db.execute("SELECT node_id FROM replicas WHERE chunk_id=?", (chunk_id,)).fetchall()
    live = live_nodes()
    return [r["node_id"] for r in rows if r["node_id"] in live and not live[r["node_id"]]["draining"]]


def choose_targets(count, size, exclude_nodes=(), exclude_machines=(), planned=None):
    """Escolhe `count` nós distintos. Primeiro máquinas distintas; se faltarem máquinas, discos distintos.
    Retorna (lista de nós, aviso ou None)."""
    planned = planned if planned is not None else {}
    cands = []
    for i, n in live_nodes(include_suspect=False).items():
        if i in exclude_nodes or n["draining"]:
            continue
        used = n["used"] + planned.get(i, 0)
        if n["total"] and (used + size) / n["total"] > DISK_LIMIT:
            continue                                   # RF7: disco acima do limite não recebe réplicas
        cands.append((n["total"] - used, random.random(), i))
    cands.sort(reverse=True)                           # política: mais espaço livre primeiro
    chosen, machines = [], set(exclude_machines)
    for _, _, i in cands:                              # 1ª passada: máquinas ainda não usadas
        if len(chosen) == count:
            break
        if nodes[i]["machine"] not in machines:
            chosen.append(i)
            machines.add(nodes[i]["machine"])
    warn = None
    if len(chosen) < count:                            # 2ª passada: mesma máquina, disco diferente
        for _, _, i in cands:
            if len(chosen) == count:
                break
            if i not in chosen:
                chosen.append(i)
                warn = "menos máquinas que o nível de replicação: réplicas em discos diferentes da mesma máquina"
    for i in chosen:
        planned[i] = planned.get(i, 0) + size
    return chosen, warn


def file_state(path):
    f = db.execute("SELECT replicas FROM files WHERE path=?", (path,)).fetchone()
    chunks = db.execute("SELECT id FROM chunks WHERE path=?", (path,)).fetchall()
    worst, recovering = None, False
    for c in chunks:
        live = len(chunk_live_replicas(c["id"]))
        worst = live if worst is None else min(worst, live)
        recovering = recovering or c["id"] in inflight
    if worst is None or worst >= f["replicas"]:
        return "íntegro"
    if worst == 0:
        return "perdido"
    return "em recuperação" if recovering else "sub-replicado"


def file_meta(path):
    f = db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
    if not f:
        raise HTTPException(404, "arquivo não encontrado")
    chunks = []
    live = live_nodes()
    for c in db.execute("SELECT * FROM chunks WHERE path=? ORDER BY idx", (path,)).fetchall():
        reps = [r["node_id"] for r in db.execute("SELECT node_id FROM replicas WHERE chunk_id=?", (c["id"],))]
        chunks.append({"id": c["id"], "index": c["idx"], "size": c["size"], "sha256": c["sha256"],
                       "replicas": [{"node": r, "url": nodes[r]["url"] if r in nodes else None,
                                     "status": node_status(nodes[r]) if r in nodes else "dead"} for r in reps],
                       "live_replicas": len([r for r in reps if r in live])})
    return {"path": path, "size": f["size"], "sha256": f["sha256"], "mtime": f["mtime"], "replicas": f["replicas"],
            "version": f["version"], "state": file_state(path), "chunks": chunks}


def ensure_parents(path):
    parent = posixpath.dirname(path)
    while parent not in ("/", ""):
        db.execute("INSERT OR IGNORE INTO dirs VALUES (?)", (parent,))
        nxt = posixpath.dirname(parent)
        if nxt == parent:
            break
        parent = nxt


def drop_file_rows(path):
    """Remove metadados de um arquivo e agenda a limpeza dos blocos nos nós."""
    for c in db.execute("SELECT id FROM chunks WHERE path=?", (path,)).fetchall():
        for r in db.execute("SELECT node_id FROM replicas WHERE chunk_id=?", (c["id"],)).fetchall():
            garbage.setdefault(r["node_id"], set()).add(c["id"])
        db.execute("DELETE FROM replicas WHERE chunk_id=?", (c["id"],))
        db.execute("DELETE FROM chunks WHERE id=?", (c["id"],))
    db.execute("DELETE FROM files WHERE path=?", (path,))


# ------------------------------------------------------------------ nós: registro e heartbeat
class NodeInfo(BaseModel):
    id: str
    url: str
    machine: str
    disk: str = "d1"
    total: int = 0
    used: int = 0
    chunks: dict = {}   # chunk_id -> sha256 (relatório completo no registro, para reconciliação)


def reconcile(node_id, reported: dict):
    """RF6: nó que (re)aparece. Blocos conhecidos e íntegros são aproveitados; desconhecidos, obsoletos
    (arquivo removido ou substituído) ou com hash diferente vão para descarte."""
    keep, drop = 0, []
    planned = {c for p in pending.values() for c in p["chunk_ids"]}
    for cid, sha in reported.items():
        row = db.execute("SELECT sha256 FROM chunks WHERE id=?", (cid,)).fetchone()
        if row and sha == row["sha256"]:
            db.execute("INSERT OR IGNORE INTO replicas VALUES (?,?)", (cid, node_id))
            keep += 1
        elif cid not in planned:
            drop.append(cid)
    log(C, "NODE_RECONCILED", node=node_id, kept=keep, discarded=len(drop))
    return drop


@app.post("/nodes/register")
def register(n: NodeInfo):
    with lock:
        known = n.id in nodes
        prev = nodes.get(n.id, {})
        nodes[n.id] = {"url": n.url, "machine": n.machine, "disk": n.disk, "total": n.total, "used": n.used,
                       "last_hb": time.time(), "draining": prev.get("draining", False), "prev_status": "alive"}
        drop = reconcile(n.id, n.chunks)
        garbage.setdefault(n.id, set()).update(drop)
        log(C, "NODE_REGISTERED" if not known else "NODE_REREGISTERED", node=n.id, machine=n.machine, disk=n.disk,
            total=n.total, chunks=len(n.chunks))
        return {"ok": True, "delete": list(garbage.pop(n.id, []))}


class Heartbeat(BaseModel):
    id: str
    used: int
    total: int
    chunks: list | None = None


@app.post("/nodes/heartbeat")
def heartbeat(h: Heartbeat):
    with lock:
        n = nodes.get(h.id)
        if not n:
            raise HTTPException(404, "nó desconhecido: registre-se")   # o nó se registra de novo (ex.: controlador reiniciou)
        n.update(used=h.used, total=h.total, last_hb=time.time())
        delete = set(garbage.pop(h.id, set()))
        if h.chunks is not None:                                       # relatório periódico: descarta órfãos
            known = {r["id"] for r in db.execute("SELECT id FROM chunks")}
            planned = {c for p in pending.values() for c in p["chunk_ids"]}
            delete |= {c for c in h.chunks if c not in known and c not in planned}
        return {"delete": list(delete)}


@app.post("/nodes/{node_id}/drain")
def drain(node_id: str):
    with lock:
        if node_id not in nodes:
            raise HTTPException(404, "nó desconhecido")
        nodes[node_id]["draining"] = True
        log(C, "NODE_DRAIN_STARTED", node=node_id)
        return {"ok": True}


@app.post("/nodes/{node_id}/undrain")
def undrain(node_id: str):
    with lock:
        if node_id not in nodes:
            raise HTTPException(404, "nó desconhecido")
        nodes[node_id]["draining"] = False
        return {"ok": True}


# ------------------------------------------------------------------ escrita em duas fases
class ChunkSpec(BaseModel):
    index: int
    size: int
    sha256: str


class Allocate(BaseModel):
    path: str
    size: int
    sha256: str
    chunks: list[ChunkSpec]
    replicas: int | None = None


@app.post("/files/allocate")
def allocate(req: Allocate):
    path = norm(req.path)
    n_rep = req.replicas or REPLICATION
    with lock:
        if db.execute("SELECT 1 FROM dirs WHERE path=?", (path,)).fetchone():
            raise HTTPException(409, "já existe um diretório com esse nome")
        version = uuid.uuid4().hex[:12]
        planned, targets, warnings = {}, {}, []
        for c in req.chunks:
            chosen, warn = choose_targets(n_rep, c.size, planned=planned)
            if len(chosen) < n_rep:
                if not ALLOW_UNDER or len(chosen) == 0:
                    log(C, "WRITE_REJECTED", file=path, reason="nós insuficientes", wanted=n_rep, available=len(chosen))
                    raise HTTPException(507, f"nós insuficientes: pedidos {n_rep}, disponíveis {len(chosen)}"
                                             + (" (política: rejeitar)" if not ALLOW_UNDER else ""))
                warnings.append(f"bloco {c.index}: só {len(chosen)} de {n_rep} nós: gravação ficará SUB-REPLICADA")
            if warn:
                warnings.append(warn)
            targets[c.index] = [{"id": i, "url": nodes[i]["url"]} for i in chosen]
        chunk_ids = {c.index: f"{version}-{c.index}" for c in req.chunks}
        pending[version] = {"path": path, "size": req.size, "sha256": req.sha256, "replicas": n_rep,
                            "created": time.time(), "chunks": {c.index: c for c in req.chunks},
                            "chunk_ids": set(chunk_ids.values())}
        log(C, "WRITE_ALLOCATED", file=path, version=version, chunks=len(req.chunks), replicas=n_rep)
        return {"version": version, "chunk_ids": chunk_ids, "targets": targets, "write_quorum": WRITE_QUORUM,
                "warnings": sorted(set(warnings))}


class Commit(BaseModel):
    version: str
    stored: dict   # índice do bloco (str) -> lista de ids de nós que confirmaram o hash


@app.post("/files/commit")
def commit(req: Commit):
    with lock:
        p = pending.get(req.version)
        if not p:
            raise HTTPException(404, "alocação desconhecida ou expirada")
        need = min(WRITE_QUORUM, p["replicas"])
        for idx in p["chunks"]:
            confirmed = req.stored.get(str(idx), [])
            if len(confirmed) < need:
                pending.pop(req.version)
                log(C, "WRITE_ABORTED", file=p["path"], version=req.version, chunk=idx, confirmed=len(confirmed))
                raise HTTPException(503, f"quórum de escrita não atingido no bloco {idx} "
                                         f"({len(confirmed)}/{need}); gravação desfeita")
        path = p["path"]
        try:                                           # troca atômica da versão: tudo ou nada
            db.execute("BEGIN")
            drop_file_rows(path)
            ensure_parents(path)
            db.execute("INSERT INTO files VALUES (?,?,?,?,?,?)",
                       (path, req.version, p["size"], p["sha256"], time.time(), p["replicas"]))
            for idx, spec in p["chunks"].items():
                cid = f"{req.version}-{idx}"
                db.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (cid, path, idx, spec.size, spec.sha256))
                for node_id in req.stored.get(str(idx), []):
                    db.execute("INSERT OR IGNORE INTO replicas VALUES (?,?)", (cid, node_id))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        pending.pop(req.version)
        stats["files_put"] += 1
        state = file_state(path)
        log(C, "FILE_COMMITTED", file=path, version=req.version, state=state)
        return {"path": path, "state": state}


# ------------------------------------------------------------------ leitura, diretórios, remoção
@app.get("/files/stat")
def stat(path: str):
    with lock:
        return file_meta(norm(path))


@app.delete("/files")
def remove(path: str):
    path = norm(path)
    with lock:
        if not db.execute("SELECT 1 FROM files WHERE path=?", (path,)).fetchone():
            raise HTTPException(404, "arquivo não encontrado")
        db.execute("BEGIN")
        drop_file_rows(path)
        db.execute("COMMIT")
        log(C, "FILE_REMOVED", file=path)
        return {"ok": True}


class Move(BaseModel):
    src: str
    dst: str


@app.post("/files/move")
def move(m: Move):
    src, dst = norm(m.src), norm(m.dst)
    with lock:
        if not db.execute("SELECT 1 FROM files WHERE path=?", (src,)).fetchone():
            raise HTTPException(404, "origem não encontrada")
        if db.execute("SELECT 1 FROM dirs WHERE path=?", (dst,)).fetchone():
            dst = posixpath.join(dst, posixpath.basename(src))   # mover para dentro de um diretório
        db.execute("BEGIN")
        drop_file_rows(dst)                 # sobrescreve destino existente
        ensure_parents(dst)
        db.execute("UPDATE files SET path=? WHERE path=?", (dst, src))
        db.execute("UPDATE chunks SET path=? WHERE path=?", (dst, src))
        db.execute("COMMIT")
        log(C, "FILE_MOVED", file=src, to=dst)
        return {"path": dst}


@app.get("/dirs")
def ls(path: str = "/"):
    path = norm(path)
    with lock:
        if not db.execute("SELECT 1 FROM dirs WHERE path=?", (path,)).fetchone():
            raise HTTPException(404, "diretório não encontrado")
        out, prefix = [], path.rstrip("/") + "/"
        for d in db.execute("SELECT path FROM dirs WHERE path LIKE ? AND path<>'/'", (prefix + "%",)):
            if "/" not in d["path"][len(prefix):]:
                out.append({"name": d["path"][len(prefix):], "type": "dir"})
        for f in db.execute("SELECT * FROM files WHERE path LIKE ?", (prefix + "%",)):
            if "/" not in f["path"][len(prefix):]:
                out.append({"name": f["path"][len(prefix):], "type": "file", "size": f["size"],
                            "mtime": f["mtime"], "state": file_state(f["path"])})
        return sorted(out, key=lambda e: (e["type"], e["name"]))


@app.post("/dirs")
def mkdir(path: str):
    path = norm(path)
    with lock:
        if db.execute("SELECT 1 FROM files WHERE path=?", (path,)).fetchone():
            raise HTTPException(409, "já existe um arquivo com esse nome")
        ensure_parents(path + "/x")
        db.execute("INSERT OR IGNORE INTO dirs VALUES (?)", (path,))
        return {"ok": True}


@app.delete("/dirs")
def rmdir(path: str):
    path = norm(path)
    with lock:
        if path == "/":
            raise HTTPException(400, "não é possível remover a raiz")
        prefix = path + "/"
        if db.execute("SELECT 1 FROM dirs WHERE path LIKE ?", (prefix + "%",)).fetchone() or \
           db.execute("SELECT 1 FROM files WHERE path LIKE ?", (prefix + "%",)).fetchone():
            raise HTTPException(409, "diretório não está vazio")
        db.execute("DELETE FROM dirs WHERE path=?", (path,))
        return {"ok": True}


class Corrupt(BaseModel):
    chunk_id: str
    node_id: str


@app.post("/report-corrupt")
def report_corrupt(r: Corrupt):
    """Cliente (leitura) ou nó (scrubbing) reporta réplica corrompida: descartada; a re-replicação a substitui."""
    with lock:
        db.execute("DELETE FROM replicas WHERE chunk_id=? AND node_id=?", (r.chunk_id, r.node_id))
        garbage.setdefault(r.node_id, set()).add(r.chunk_id)
        stats["corrupt_reports"] += 1
        log(C, "REPLICA_CORRUPT_REPORTED", chunk=r.chunk_id, node=r.node_id)
        return {"ok": True}


# ------------------------------------------------------------------ visibilidade e métricas (RF11)
def states_summary():
    out = {"íntegro": 0, "sub-replicado": 0, "em recuperação": 0, "perdido": 0}
    for f in db.execute("SELECT path FROM files").fetchall():
        out[file_state(f["path"])] += 1
    return out


@app.get("/status")
def status():
    with lock:
        ns = []
        for i, n in sorted(nodes.items()):
            held = db.execute("SELECT COUNT(*) c FROM replicas WHERE node_id=?", (i,)).fetchone()["c"]
            ns.append({"id": i, "machine": n["machine"], "disk": n["disk"], "status": node_status(n),
                       "draining": n["draining"], "total": n["total"], "used": n["used"],
                       "used_pct": round(100 * n["used"] / n["total"], 1) if n["total"] else None,
                       "chunks": held, "last_heartbeat_s": round(time.time() - n["last_hb"], 1)})
        return {"nodes": ns, "files_by_state": states_summary(),
                "rereplications_in_progress": [{"chunk": c, "source": i["source"], "target": i["target"],
                                               "live_replicas": i["live_replicas"]} for c, i in inflight.items()],
                "pending_writes": len(pending)}


@app.get("/metrics")
def metrics():
    with lock:
        nstat = [node_status(n) for n in nodes.values()]
        n_files = db.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
        logical = db.execute("SELECT COALESCE(SUM(size),0) s FROM files").fetchone()["s"]
        physical = sum(n["used"] for n in nodes.values())
        return {"nodes": {s: nstat.count(s) for s in ("alive", "suspect", "dead")}, "files": n_files,
                "files_by_state": states_summary(), "logical_bytes": logical, "physical_bytes": physical,
                "storage_overhead": round(physical / logical, 2) if logical else None,
                "rereplication": {"bytes_copied": stats["bytes_copied"], "copies_done": stats["copies_done"],
                                  "copies_failed": stats["copies_failed"], "in_progress": len(inflight),
                                  "recovery_times_s": stats["recovery_s"],
                                  "min_live_replicas_seen": stats["min_live_replicas"]},
                "corrupt_reports": stats["corrupt_reports"], "files_put": stats["files_put"],
                "node_dead_events": stats["node_dead_events"],
                "config": {"N": REPLICATION, "W": WRITE_QUORUM, "disk_limit": DISK_LIMIT,
                           "max_rereplication": MAX_REREPL, "heartbeat_suspect_s": HB_SUSPECT,
                           "heartbeat_dead_s": HB_DEAD}}


@app.get("/health")
def health():
    return {"status": "ok", "nodes": len(nodes)}


@app.get("/config")
def config():
    return {"chunk_mb": CHUNK_MB, "replication": REPLICATION, "write_quorum": WRITE_QUORUM}


# ------------------------------------------------------------------ laços de fundo
def monitor_loop():
    """Detecção de falhas por timeout de heartbeat; transições são logadas com hora exata."""
    names = {"alive": "NODE_ALIVE", "suspect": "NODE_SUSPECT", "dead": "NODE_DEAD"}
    while True:
        time.sleep(1)
        with lock:
            for i, n in nodes.items():
                st = node_status(n)
                if st != n["prev_status"]:
                    log(C, names[st], node=i, since_last_heartbeat_s=round(time.time() - n["last_hb"], 1))
                    if st == "dead":
                        stats["node_dead_events"].append({"node": i, "ts": time.time()})
                    n["prev_status"] = st
            for v in [v for v, p in pending.items() if time.time() - p["created"] > 120]:
                log(C, "WRITE_EXPIRED", version=v, file=pending[v]["path"])   # gravação incompleta: desfeita
                pending.pop(v)


def copy_task(chunk_id, source, target, size, sha):
    t0 = time.time()
    try:
        r = requests.post(f"{nodes[target]['url']}/replicate", timeout=120,
                          json={"chunk_id": chunk_id, "source_url": nodes[source]["url"], "sha256": sha})
        r.raise_for_status()
        with lock:
            if db.execute("SELECT 1 FROM chunks WHERE id=?", (chunk_id,)).fetchone():
                db.execute("INSERT OR IGNORE INTO replicas VALUES (?,?)", (chunk_id, target))
            stats["bytes_copied"] += size
            stats["copies_done"] += 1
        log(C, "REREPLICATION_DONE", chunk=chunk_id, source=source, target=target, bytes=size,
            seconds=round(time.time() - t0, 3))
    except Exception as e:
        with lock:
            stats["copies_failed"] += 1
        log(C, "REREPLICATION_FAILED", chunk=chunk_id, source=source, target=target, error=str(e)[:120])
    finally:
        with lock:
            inflight.pop(chunk_id, None)


def replication_loop():
    """RF5: restabelece N réplicas. Prioridade: blocos com menos réplicas vivas. Limite: MAX_REREPL cópias paralelas."""
    while True:
        time.sleep(1)
        try:
            replication_pass()
        except Exception as e:  # o laço nunca morre
            log(C, "REPLICATION_LOOP_ERROR", error=str(e)[:200])


def replication_pass():
    with lock:
        work = []
        rows = db.execute("SELECT c.id, c.size, c.sha256, f.replicas FROM chunks c JOIN files f ON f.path=c.path").fetchall()
        for c in rows:
            live = chunk_live_replicas(c["id"])
            if len(live) < c["replicas"] and c["id"] not in inflight:
                work.append((len(live), c))
            elif len(live) > c["replicas"]:
                # excesso (ex.: nó voltou depois da re-replicação): remove réplicas extras do nó mais cheio
                for extra in sorted(live, key=lambda i: nodes[i]["used"], reverse=True)[: len(live) - c["replicas"]]:
                    db.execute("DELETE FROM replicas WHERE chunk_id=? AND node_id=?", (c["id"], extra))
                    garbage.setdefault(extra, set()).add(c["id"])
                    log(C, "REPLICA_TRIMMED", chunk=c["id"], node=extra)
        degraded = len(work) > 0 or bool(inflight)
        if degraded and stats["degraded_since"] is None:
            stats["degraded_since"] = time.time()
            log(C, "DEGRADED_STARTED", under_replicated_chunks=len(work))
        if not degraded and stats["degraded_since"] is not None:
            dur = round(time.time() - stats["degraded_since"], 2)
            stats["recovery_s"].append(dur)
            stats["degraded_since"] = None
            log(C, "FULL_REPLICATION_RESTORED", seconds=dur)
        if work:
            low = min(w[0] for w in work)
            stats["min_live_replicas"] = low if stats["min_live_replicas"] is None else min(stats["min_live_replicas"], low)
        work.sort(key=lambda w: w[0])                           # menos réplicas vivas primeiro
        for live_count, c in work:
            if len(inflight) >= MAX_REREPL:
                break
            holders = [r["node_id"] for r in db.execute("SELECT node_id FROM replicas WHERE chunk_id=?", (c["id"],))]
            alive = live_nodes(include_suspect=False)
            sources = [h for h in holders if h in alive]
            if not sources:
                continue                                        # sem cópia viva por enquanto (o nó pode voltar)
            live = chunk_live_replicas(c["id"])
            targets, _ = choose_targets(1, c["size"], exclude_nodes=set(holders),
                                        exclude_machines={nodes[i]["machine"] for i in live})
            if not targets:
                continue
            src, tgt = random.choice(sources), targets[0]
            inflight[c["id"]] = {"source": src, "target": tgt, "live_replicas": live_count}
            log(C, "REREPLICATION_STARTED", chunk=c["id"], source=src, target=tgt, live_replicas=live_count)
            pool.submit(copy_task, c["id"], src, tgt, c["size"], c["sha256"])


@app.on_event("startup")
def start_background():
    # metadados recarregados do SQLite: reiniciar o controlador não exige recriar o estado (RF10)
    log(C, "CONTROLLER_STARTED", files=db.execute("SELECT COUNT(*) c FROM files").fetchone()["c"],
        N=REPLICATION, W=WRITE_QUORUM)
    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=replication_loop, daemon=True).start()
