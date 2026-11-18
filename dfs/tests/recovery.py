"""E7 (recuperação em escala), E8 (nó novo sob carga) e E9 (desempenho sob falha). Rodam no host.

Uso (em dfs/):  python tests/recovery.py e7|e8|e9
Saída: tests/results/E7_recuperacao.json, E8_no_novo.json, E9_events.json + E9_timeline.json
Registra a hora de cada ação (falha injetada, detecção, recuperação concluída) em época UNIX.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import functional as f  # noqa: E402  (reaproveita helpers: dc, cli, status, metrics, wait_for, controller_events)

RES = f.RES


def put_volume(mb, prefix):
    """Grava `mb` MB em arquivos de 10 MB (N=3) e devolve os caminhos."""
    src = f.make_file("vol10m.bin", 10 * 1024 * 1024)
    paths = []
    for i in range(mb // 10):
        p = f"{prefix}/f{i}.bin"
        f.cli("put", "/files/vol10m.bin", p)
        paths.append(p)
    return paths


def wipe(prefix):
    import requests
    try:
        for e in requests.get(f"{f.CTRL}/dirs", params={"path": prefix}, timeout=10).json():
            requests.delete(f"{f.CTRL}/files", params={"path": f"{prefix}/{e['name']}"}, timeout=10)
    except Exception:
        pass


def settle(timeout=180):
    """Espera todos os nós vivos e sem re-replicação pendente."""
    return f.wait_for(lambda: all(n["status"] == "alive" for n in f.status()["nodes"] if n["id"] != "node6")
                      and not f.status()["rereplications_in_progress"]
                      and f.status()["files_by_state"]["íntegro"] == sum(f.status()["files_by_state"].values()), timeout)


def recovery_once(mb, tag):
    wipe("/e7")
    settle()
    put_volume(mb, "/e7")
    time.sleep(3)
    st = f.status()
    victim = max((n for n in st["nodes"] if n["id"] != "node6"), key=lambda n: n["chunks"])
    m0 = f.metrics()["rereplication"]
    t_fail = time.time()
    f.dc("stop", victim["id"])
    t_dead = f.wait_for(lambda: next(n for n in f.status()["nodes"] if n["id"] == victim["id"])["status"] == "dead", 60)
    t_ok = f.wait_for(lambda: not f.status()["rereplications_in_progress"]
                      and f.status()["files_by_state"]["íntegro"] == sum(f.status()["files_by_state"].values()), 600)
    m1 = f.metrics()["rereplication"]
    total = (t_dead or 0) + (t_ok or 0)      # da falha até todos os arquivos voltarem a N réplicas
    copied = m1["bytes_copied"] - m0["bytes_copied"]
    copy_s = max(t_ok or 0, 1e-6)            # só a fase de cópia (depois da detecção)
    f.dc("start", victim["id"])
    settle()
    row = {"volume_mb": mb, "no": victim["id"], "blocos_no_no": victim["chunks"], "hora_falha": t_fail,
           "detectado_s": t_dead, "recuperado_s": total, "bytes_copiados": copied,
           "vazao_rereplicacao_mb_s": copied / 1048576 / copy_s, "tag": tag}
    print(row, flush=True)
    return row


def e7():
    rows = []
    for mb in (50, 100, 200):
        for rep in range(3):
            rows.append(recovery_once(mb, "banda_livre"))
    # limite de banda de re-replicação: 8 MB/s por cópia (recria os nós com a variável; os blocos persistem nos volumes)
    f.sh("docker", "compose", "up", "-d", "node1", "node2", "node3", "node4", "node5", env={"REPLICATION_MBPS": "8"})
    f.wait_for(lambda: all(n["status"] == "alive" for n in f.status()["nodes"] if n["id"] != "node6"), 60)
    time.sleep(5)
    for rep in range(3):
        rows.append(recovery_once(100, "limite_8MBps"))
    f.sh("docker", "compose", "up", "-d", "node1", "node2", "node3", "node4", "node5", env={"REPLICATION_MBPS": "0"})
    json.dump(rows, open(f"{RES}/E7_recuperacao.json", "w"), indent=1)


def start_loadgen(seconds, out):
    return subprocess.Popen(["docker", "compose", "run", "--rm", "-T", "--entrypoint", "python", "client",
                             "/tests/perf.py", "loadgen", str(seconds), f"/tests/results/{out}"],
                            cwd=f.ROOT, env=f.ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def e8():
    """Nó novo entra durante a carga: tempo para ser descoberto e para receber o primeiro bloco; efeito na latência."""
    f.dc("rm", "-sf", "node6")
    f.sh("docker", "volume", "rm", "-f", "dfs_node6-data")   # o nó 6 entra VAZIO: o 1º bloco medido é de gravação nova
    time.sleep(2)
    p = start_loadgen(50, "E8_events.json")
    time.sleep(15)
    t_join = time.time()
    f.dc("--profile", "extra", "up", "-d", "node6")
    t_disc = f.wait_for(lambda: any(n["id"] == "node6" and n["status"] == "alive" for n in f.status()["nodes"]), 60)
    t_data = f.wait_for(lambda: any(n["id"] == "node6" and n["chunks"] > 0 for n in f.status()["nodes"]), 60)
    p.wait()
    out = {"hora_entrada": t_join, "descoberto_em_s": t_disc, "primeiro_bloco_em_s": t_data and t_data + (t_disc or 0)}
    json.dump(out, open(f"{RES}/E8_no_novo.json", "w"), indent=1)
    print(out)


def e9():
    """Carga contínua do início ao fim; derruba um nó em t≈20s, religa em t≈70s."""
    f.dc("--profile", "extra", "up", "-d", "node6")
    settle()
    p = start_loadgen(100, "E9_events.json")
    time.sleep(20)
    victim = max((n for n in f.status()["nodes"] if n["id"] != "node6"), key=lambda n: n["chunks"])["id"]
    t_fail = time.time()
    f.dc("stop", victim)
    t_dead = f.wait_for(lambda: next(n for n in f.status()["nodes"] if n["id"] == victim)["status"] == "dead", 60)
    t_rec = f.wait_for(lambda: not f.status()["rereplications_in_progress"] and
                       f.status()["files_by_state"]["íntegro"] == sum(f.status()["files_by_state"].values()), 120)
    time.sleep(max(0, 50 - (time.time() - t_fail)))
    t_back = time.time()
    f.dc("start", victim)
    p.wait()
    out = {"no": victim, "hora_falha": t_fail, "hora_detectado": t_fail + (t_dead or 0),
           "hora_recuperado": t_fail + (t_rec or 0) + (t_dead or 0) if t_rec else None, "hora_no_volta": t_back}
    json.dump(out, open(f"{RES}/E9_timeline.json", "w"), indent=1)
    print(out)


if __name__ == "__main__":
    {"e7": e7, "e8": e8, "e9": e9}[sys.argv[1]]()
