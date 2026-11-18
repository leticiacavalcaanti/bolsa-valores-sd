"""Cliente CLI. Divide o arquivo em blocos, calcula os hashes, (opcionalmente) cifra e transfere os dados
DIRETAMENTE para os nós indicados pelo controlador (plano de dados); o controlador só vê metadados.

Uso: python -m dfs.client <comando> [args]
  put LOCAL REMOTO [--replicas N]   get REMOTO LOCAL   rm REMOTO   mv ORIGEM DESTINO   ls [DIR]
  mkdir DIR   rmdir DIR   stat REMOTO   status   metrics   drain NO   undrain NO

Criptografia (RF9), controlada por ENCRYPTION=on|off:
- A cifra (AES-256-GCM, biblioteca `cryptography`) ocorre NO CLIENTE: os nós e o controlador nunca veem texto
  claro nem a chave. A chave fica só com o cliente (DFS_KEY em hex, ou o arquivo apontado por DFS_KEY_FILE).
- O hash de cada bloco é calculado sobre o conteúdo CIFRADO (é o que os nós guardam), assim eles verificam
  integridade e fazem scrubbing sem a chave. O hash do arquivo é sobre o texto claro (verificação ponta a ponta).
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .common import env, sha256_hex

CONTROLLER = env("CONTROLLER_URL", "http://controller:9000")
ENCRYPTION = env("ENCRYPTION", "off").lower() == "on"


def api(method, path, **kw):
    r = requests.request(method, CONTROLLER + path, timeout=60, **kw)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise SystemExit(f"ERRO {r.status_code}: {detail}")
    return r.json()


def get_key():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401  (valida a dependência)
    if os.environ.get("DFS_KEY"):
        return bytes.fromhex(os.environ["DFS_KEY"])
    path = env("DFS_KEY_FILE", "/files/.dfs.key")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(os.urandom(32))
    return open(path, "rb").read()


def encrypt(key, plain: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plain, None)


def decrypt(key, blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


def put(local, remote, replicas=None):
    t0 = time.time()
    chunk_bytes = int(env("CHUNK_MB", api("GET", "/config")["chunk_mb"], float) * 1024 * 1024)
    key = get_key() if ENCRYPTION else None
    data = open(local, "rb").read()
    payloads = []
    for i in range(0, max(len(data), 1), chunk_bytes):
        part = data[i:i + chunk_bytes]
        payloads.append(encrypt(key, part) if ENCRYPTION else part)
    specs = [{"index": i, "size": len(p), "sha256": sha256_hex(p)} for i, p in enumerate(payloads)]
    alloc = api("POST", "/files/allocate", json={"path": remote, "size": len(data), "sha256": sha256_hex(data),
                                                 "chunks": specs, "replicas": replicas})
    for w in alloc["warnings"]:
        print("AVISO:", w)

    def upload(task):
        idx, node = task
        chunk_id = alloc["chunk_ids"][str(idx)]
        try:
            r = requests.put(f"{node['url']}/chunks/{chunk_id}", data=payloads[idx], timeout=60,
                             headers={"X-Sha256": specs[idx]["sha256"]})
            return idx, node["id"], r.status_code == 200 and r.json().get("sha256") == specs[idx]["sha256"]
        except Exception:
            return idx, node["id"], False

    tasks = [(int(idx), n) for idx, nodes in alloc["targets"].items() for n in nodes]
    stored = {}
    with ThreadPoolExecutor(8) as ex:                   # envio paralelo do cliente aos N nós de cada bloco
        for idx, node_id, ok in ex.map(upload, tasks):
            if ok:
                stored.setdefault(str(idx), []).append(node_id)
    res = api("POST", "/files/commit", json={"version": alloc["version"], "stored": stored})
    secs = time.time() - t0
    print(f"OK {remote}: {len(data)} bytes, {len(payloads)} bloco(s), estado={res['state']}, "
          f"{secs:.2f}s ({len(data) / 1048576 / max(secs, 1e-9):.1f} MB/s){' [cifrado]' if ENCRYPTION else ''}")


def get(remote, local):
    meta = api("GET", "/files/stat", params={"path": remote})
    key = get_key() if ENCRYPTION else None
    out = bytearray()
    for c in meta["chunks"]:
        blob = None
        # prefere réplicas em nós vivos; tenta as demais se falhar ou se o hash não conferir
        for r in sorted(c["replicas"], key=lambda r: r["status"] != "alive"):
            if r["status"] == "dead" or not r["url"]:
                continue
            try:
                resp = requests.get(f"{r['url']}/chunks/{c['id']}", timeout=30)
                if resp.status_code == 200 and sha256_hex(resp.content) == c["sha256"]:   # RF4b: verifica em toda leitura
                    blob = resp.content
                    break
                if resp.status_code == 200:
                    print(f"AVISO: réplica corrompida de {c['id']} em {r['node']}; tentando outra e reportando")
                    requests.post(f"{CONTROLLER}/report-corrupt", json={"chunk_id": c["id"], "node_id": r["node"]}, timeout=5)
            except Exception:
                continue
        if blob is None:
            raise SystemExit(f"ERRO: nenhuma réplica íntegra do bloco {c['index']} disponível")
        out += decrypt(key, blob) if ENCRYPTION else blob
    if sha256_hex(bytes(out)) != meta["sha256"]:
        raise SystemExit("ERRO: hash do arquivo final não confere")
    open(local, "wb").write(out)
    print(f"OK {remote} -> {local}: {len(out)} bytes, sha256 verificado")


def show_stat(remote):
    m = api("GET", "/files/stat", params={"path": remote})
    print(f"{m['path']}\n  tamanho: {m['size']} bytes\n  data: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(m['mtime']))}"
          f"\n  sha256: {m['sha256']}\n  estado: {m['state']}\n  réplicas desejadas (N): {m['replicas']}")
    for c in m["chunks"]:
        locs = ", ".join(f"{r['node']}({r['status']})" for r in c["replicas"])
        print(f"  bloco {c['index']} [{c['id']}] {c['size']} B, {c['live_replicas']} vivas: {locs}")


def show_status():
    s = api("GET", "/status")
    print(f"{'NÓ':8}{'MÁQUINA':10}{'DISCO':6}{'ESTADO':10}{'USO':>8}{'BLOCOS':>8}  OBS")
    for n in s["nodes"]:
        print(f"{n['id']:8}{n['machine']:10}{n['disk']:6}{n['status']:10}{str(n['used_pct']) + '%':>8}{n['chunks']:>8}  "
              f"{'drenando' if n['draining'] else ''}")
    print("arquivos por estado:", s["files_by_state"])
    print("re-replicações em andamento:", s["rereplications_in_progress"] or "nenhuma")


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "put":
        reps = int(args[args.index("--replicas") + 1]) if "--replicas" in args else None
        put(args[0], args[1], reps)
    elif cmd == "get":
        get(args[0], args[1])
    elif cmd == "rm":
        api("DELETE", "/files", params={"path": args[0]}); print("removido")
    elif cmd == "mv":
        print("movido para", api("POST", "/files/move", json={"src": args[0], "dst": args[1]})["path"])
    elif cmd == "ls":
        for e in api("GET", "/dirs", params={"path": args[0] if args else "/"}):
            print(f"{e['type']:5} {e['name']:30} {e.get('size', ''):>12} {e.get('state', '')}")
    elif cmd == "mkdir":
        api("POST", "/dirs", params={"path": args[0]}); print("criado")
    elif cmd == "rmdir":
        api("DELETE", "/dirs", params={"path": args[0]}); print("removido")
    elif cmd == "stat":
        show_stat(args[0])
    elif cmd == "status":
        show_status()
    elif cmd == "metrics":
        print(json.dumps(api("GET", "/metrics"), indent=2, ensure_ascii=False))
    elif cmd in ("drain", "undrain"):
        api("POST", f"/nodes/{args[0]}/{cmd}"); print(f"{cmd} iniciado em {args[0]}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
