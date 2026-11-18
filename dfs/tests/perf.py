"""Testes de desempenho (rodam DENTRO da rede do Docker, como o cliente real):
  E2 mais clientes | E3 tamanho dos arquivos | E5 custo da replicação (N) | E6 custo de criptografia | loadgen (E8/E9)

Uso (em dfs/):
  docker compose run --rm -T --entrypoint python client /tests/perf.py e2|e3|e5|e6
  docker compose run --rm -T --entrypoint python client /tests/perf.py loadgen SEGUNDOS ARQUIVO_SAIDA
Cada experimento repete REPS vezes (descarta a 1ª, de aquecimento) e reporta média ± IC 95% (t de Student).
"""
import contextlib
import io
import json
import math
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, "/srv")
from dfs import client  # noqa: E402

CTRL = os.environ.get("CONTROLLER_URL", "http://controller:9000")
OUT = "/tests/results"
REPS = int(os.environ.get("REPS", 4))   # 1 de aquecimento + 3 válidas
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57}
os.makedirs(OUT, exist_ok=True)
os.makedirs("/tmp/perf", exist_ok=True)


def ci(values):
    n = len(values)
    if n < 2:
        return (values[0] if values else 0.0), 0.0
    return statistics.mean(values), T95.get(n - 1, 1.96) * statistics.stdev(values) / math.sqrt(n)


def pct(v, p):
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * p / 100))] if s else 0.0


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def mkfile(name, size):
    p = f"/tmp/perf/{name}"
    if not os.path.exists(p) or os.path.getsize(p) != size:
        open(p, "wb").write(os.urandom(size))
    return p


def timed_put(local, remote, replicas=None):
    t0 = time.perf_counter()
    quiet(client.put, local, remote, replicas)
    return (time.perf_counter() - t0) * 1000


def timed_get(remote, local):
    t0 = time.perf_counter()
    quiet(client.get, remote, local)
    return (time.perf_counter() - t0) * 1000


def cleanup(prefix):
    for e in requests.get(f"{CTRL}/dirs", params={"path": prefix}, timeout=10).json():
        requests.delete(f"{CTRL}/files", params={"path": f"{prefix}/{e['name']}"}, timeout=10)


def purge(prefix="/perf"):
    """Remove recursivamente os arquivos de teste (evita encher os discos entre experimentos)."""
    try:
        for e in requests.get(f"{CTRL}/dirs", params={"path": prefix}, timeout=10).json():
            q = f"{prefix}/{e['name']}"
            if e["type"] == "dir":
                purge(q)
                requests.delete(f"{CTRL}/dirs", params={"path": q}, timeout=10)
            else:
                requests.delete(f"{CTRL}/files", params={"path": q}, timeout=10)
    except Exception:
        pass


def run_clients(n_clients, dur, size, tag):
    """n_clients em paralelo, cada um alternando put e get de um arquivo de `size` bytes durante `dur` s."""
    path = mkfile(f"c_{size}.bin", size)
    lat, ops, nbytes = [], [0], [0]
    lock = threading.Lock()
    stop = time.time() + dur

    def worker(i):
        k = 0
        while time.time() < stop:
            remote = f"/perf/{tag}/c{i}_{k % 3}.bin"
            try:
                a = timed_put(path, remote)
                b = timed_get(remote, f"/tmp/perf/out_{tag}_{i}.bin")
                with lock:
                    lat.extend([a, b]); ops[0] += 2; nbytes[0] += 2 * size
            except SystemExit:
                pass
            k += 1
    t0 = time.time()
    with ThreadPoolExecutor(n_clients) as ex:
        list(ex.map(worker, range(n_clients)))
    el = time.time() - t0
    purge(f"/perf/{tag}")
    return {"ops_s": ops[0] / el, "mb_s": nbytes[0] / 1048576 / el, "p50": pct(lat, 50), "p95": pct(lat, 95),
            "mean": statistics.mean(lat) if lat else 0}


def experiment(name, configs, fn, keys=("ops_s", "mb_s", "p50", "p95")):
    rows = []
    for cfg in configs:
        runs = []
        for r in range(REPS):
            res = fn(cfg, r)
            if r > 0:                       # descarta a 1ª execução (aquecimento / cache)
                runs.append(res)
            print(name, cfg, "rep", r, {k: round(v, 2) for k, v in res.items() if isinstance(v, (int, float))}, flush=True)
        row = {"config": cfg, "reps": len(runs), **{k: ci([x[k] for x in runs]) for k in keys}}
        rows.append(row)
    json.dump(rows, open(f"{OUT}/{name}.json", "w"), indent=1)
    return rows


def e2():
    requests.post(f"{CTRL}/dirs", params={"path": "/perf"})
    experiment("E2_clientes", [1, 2, 4, 8, 16],
               lambda n, r: run_clients(n, 8, 1024 * 1024, f"e2_{n}_{r}"))


def e3():
    requests.post(f"{CTRL}/dirs", params={"path": "/perf"})
    experiment("E3_tamanho", [("10KB", 10 * 1024), ("100KB", 100 * 1024), ("1MB", 1024 * 1024), ("10MB", 10 * 1024 * 1024),
                              ("50MB", 50 * 1024 * 1024)],
               lambda cfg, r: run_clients(4, 8, cfg[1], f"e3_{cfg[0]}_{r}"))


def e5():
    """Custo da replicação: N = 1..4 (tempo de escrita, vazão, espaço consumido, leitura)."""
    requests.post(f"{CTRL}/dirs", params={"path": "/perf"})
    path = mkfile("n10m.bin", 10 * 1024 * 1024)
    rows = []

    def one(n, r):
        remote = f"/perf/e5_{n}_{r}.bin"
        w = timed_put(path, remote, n)
        meta = requests.get(f"{CTRL}/files/stat", params={"path": remote}).json()
        phys = sum(c["size"] * len(c["replicas"]) for c in meta["chunks"])   # bytes realmente gravados (todas as réplicas)
        rd = timed_get(remote, "/tmp/perf/e5.out")
        requests.delete(f"{CTRL}/files", params={"path": remote})
        return {"write_ms": w, "write_mb_s": 10 / (w / 1000), "read_ms": rd, "read_mb_s": 10 / (rd / 1000),
                "overhead_x": phys / (10 * 1048576)}
    experiment("E5_replicacao", [1, 2, 3, 4], one, keys=("write_ms", "write_mb_s", "read_ms", "read_mb_s", "overhead_x"))


def e6():
    """Custo de criptografia: desliga vs liga; CPU do cliente medido por tempo de processo (CPU-s por MB)."""
    requests.post(f"{CTRL}/dirs", params={"path": "/perf"})
    path = mkfile("e6_20m.bin", 20 * 1024 * 1024)

    def one(enc, r):
        client.ENCRYPTION = enc == "ligada"
        remote = f"/perf/e6_{enc}_{r}.bin"
        c0 = time.process_time()
        w = timed_put(path, remote)
        rd = timed_get(remote, "/tmp/perf/e6.out")
        cpu = time.process_time() - c0
        requests.delete(f"{CTRL}/files", params={"path": remote})
        return {"write_mb_s": 20 / (w / 1000), "read_mb_s": 20 / (rd / 1000), "cpu_s_per_mb": cpu / 40}
    experiment("E6_cripto", ["desligada", "ligada"], one, keys=("write_mb_s", "read_mb_s", "cpu_s_per_mb"))
    client.ENCRYPTION = False


def loadgen(duration, outfile):
    """Carga contínua (4 clientes, arquivos de 1 MB) registrando CADA operação com hora, para gráfico no tempo (E8/E9)."""
    requests.post(f"{CTRL}/dirs", params={"path": "/perf"})
    path = mkfile("lg_1m.bin", 1024 * 1024)
    events, lock = [], threading.Lock()
    stop = time.time() + float(duration)

    def worker(i):
        k = 0
        while time.time() < stop:
            remote = f"/perf/lg/c{i}_{k % 4}.bin"
            for op in ("put", "get"):
                t0 = time.time()
                ok = True
                try:
                    (timed_put(path, remote) if op == "put" else timed_get(remote, f"/tmp/perf/lg_{i}.bin"))
                except SystemExit:
                    ok = False
                except Exception:
                    ok = False
                with lock:
                    events.append({"t": t0, "ms": (time.time() - t0) * 1000, "op": op, "ok": ok})
            k += 1
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(worker, range(4)))
    json.dump(events, open(outfile, "w"))
    print("loadgen: ops=", len(events), "ok=", sum(e["ok"] for e in events))


if __name__ == "__main__":
    {"e2": e2, "e3": e3, "e5": e5, "e6": e6}.get(sys.argv[1], lambda: loadgen(sys.argv[2], sys.argv[3]))() \
        if sys.argv[1] != "loadgen" else loadgen(sys.argv[2], sys.argv[3])
