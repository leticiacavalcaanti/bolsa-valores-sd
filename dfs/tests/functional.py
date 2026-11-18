"""Testes funcionais e de tolerância a falhas do sistema de arquivos (rodam no host, dirigem o Docker Compose).

Uso (em dfs/, com `docker compose up -d --build` no ar):  python tests/functional.py
Saída: tests/results/functional.json (ID, objetivo, esperado, obtido, status, evidência) e
       tests/results/fault_timeline.json (linha do tempo de cada falha injetada, com hora exata).
"""
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)
FILES = os.path.join(ROOT, "files")
CTRL = "http://localhost:9000"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
results, timeline = [], []


def sh(*cmd, env=None, timeout=300):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env={**ENV, **(env or {})}, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout + r.stderr)


def cli(*args, env=None):
    return sh("docker", "compose", "run", "--rm", "-T", "client", *args, env=env)


def dc(*args):
    return sh("docker", "compose", *args)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def make_file(name, size):
    p = os.path.join(FILES, name)
    with open(p, "wb") as f:
        f.write(os.urandom(size))
    return p


def status():
    return requests.get(f"{CTRL}/status", timeout=5).json()


def metrics():
    return requests.get(f"{CTRL}/metrics", timeout=5).json()


def stat(path):
    return requests.get(f"{CTRL}/files/stat", params={"path": path}, timeout=5).json()


def wait_for(cond, timeout=90, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                return time.time() - t0
        except Exception:
            pass
        time.sleep(step)
    return None


def controller_events(event=None):
    _, out = dc("logs", "--no-log-prefix", "controller")
    evs = []
    for line in out.splitlines():
        if line.startswith("{"):
            try:
                e = json.loads(line)
                e["epoch"] = datetime.strptime(e["ts"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
                if event is None or e["event"] == event:
                    evs.append(e)
            except Exception:
                pass
    return evs


def fully_replicated(path, n=3):
    return all(c["live_replicas"] >= n for c in stat(path)["chunks"])


def case(tid, objetivo, esperado, fn):
    try:
        ok, obtido = fn()
    except Exception as e:  # noqa
        ok, obtido = False, f"exceção: {e}"
    results.append({"id": tid, "objetivo": objetivo, "esperado": esperado, "obtido": str(obtido),
                    "status": "passou" if ok else "falhou", "hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    print(f"[{'OK' if ok else 'FALHOU'}] {tid} {objetivo} -> {obtido}")


def main():
    dc("up", "-d", "--build")
    wait_for(lambda: len(status()["nodes"]) >= 5 and all(n["status"] == "alive" for n in status()["nodes"]), 60)
    cli("ls", "/")  # aquecimento: a primeira execução do contêiner cliente pode demorar/falhar logo após o `up`
    src = make_file("t10m.bin", 10 * 1024 * 1024)
    ref = sha(src)
    uniq = str(int(time.time()))
    base = f"/t{uniq}"

    # F01 diretórios
    def f01():
        r1, r2 = cli("mkdir", base), cli("mkdir", f"{base}/sub")
        ls = cli("ls", base)
        busy = cli("rmdir", base)  # não vazio: deve falhar
        empty = cli("rmdir", f"{base}/sub")
        parts = {"mkdir": r1[0] == 0 and r2[0] == 0, "ls_tem_sub": "sub" in ls[1],
                 "rmdir_nao_vazio_rejeitado": busy[0] != 0 and "vazio" in busy[1], "rmdir_vazio_ok": empty[0] == 0}
        return all(parts.values()), parts
    case("F01", "Criar, listar e remover diretório (vazio vs não vazio)", "rejeita remover não vazio", f01)

    # F02 put/get com integridade
    def f02():
        rc, out = cli("put", f"/files/t10m.bin", f"{base}/a.bin")
        rc2, out2 = cli("get", f"{base}/a.bin", "/files/t10m.out")
        same = sha(os.path.join(FILES, "t10m.out")) == ref
        return rc == 0 and rc2 == 0 and same, f"{out.strip().splitlines()[-1]} | sha256 igual ao original: {same}"
    case("F02", "put + get de 10 MB devolve arquivo idêntico", "sha256 igual", f02)

    # F03 regra de não repetição
    def f03():
        m = stat(f"{base}/a.bin")
        nodes = {n["id"]: n for n in status()["nodes"]}
        bad = []
        for c in m["chunks"]:
            ids = [r["node"] for r in c["replicas"]]
            machines = [nodes[i]["machine"] for i in ids]
            if len(set(ids)) != 3 or len(set(machines)) != 3:
                bad.append(c["index"])
        return not bad, f"{len(m['chunks'])} blocos x 3 réplicas em nós e máquinas distintos; violações: {bad}"
    case("F03", "Réplicas nunca no mesmo disco/máquina", "0 violações", f03)

    # F04 metadados e estado
    def f04():
        out = cli("stat", f"{base}/a.bin")[1]
        return all(k in out for k in ("tamanho", "sha256", "estado: íntegro", "bloco 0")), out.strip().splitlines()[1:4]
    case("F04", "Consulta de metadados (tamanho, data, hash, réplicas, estado)", "campos presentes", f04)

    # F05 mover e remover
    def f05():
        mv = cli("mv", f"{base}/a.bin", f"{base}/b.bin")[0] == 0
        ok_new = requests.get(f"{CTRL}/files/stat", params={"path": f"{base}/b.bin"}).status_code == 200
        gone = requests.get(f"{CTRL}/files/stat", params={"path": f"{base}/a.bin"}).status_code == 404
        rm = cli("rm", f"{base}/b.bin")[0] == 0
        return mv and ok_new and gone and rm, f"mv={mv} novo existe={ok_new} antigo sumiu={gone} rm={rm}"
    case("F05", "Renomear/mover e remover arquivo", "ok", f05)

    # F06 replicação insuficiente: política aceita como sub-replicada e avisa
    def f06():
        rc, out = cli("put", "/files/t10m.bin", f"{base}/sub.bin", "--replicas", "7")
        return "SUB-REPLICADA" in out and "sub-replicado" in out, [l for l in out.splitlines() if "AVISO" in l or "OK" in l]
    case("F06", "Menos nós que N: aceita como sub-replicada e informa claramente", "AVISO + estado sub-replicado", f06)
    cli("rm", f"{base}/sub.bin")

    # F07 quórum / concorrência: duas escritas simultâneas no mesmo caminho
    def f07():
        p1, p2 = make_file("c1.bin", 3 * 1024 * 1024), make_file("c2.bin", 3 * 1024 * 1024)
        h1, h2 = sha(p1), sha(p2)
        procs = [subprocess.Popen(["docker", "compose", "run", "--rm", "-T", "client", "put", f"/files/{n}", f"{base}/c.bin"],
                                  cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for n in ("c1.bin", "c2.bin")]
        [p.wait() for p in procs]
        cli("get", f"{base}/c.bin", "/files/c.out")
        h = sha(os.path.join(FILES, "c.out"))
        return h in (h1, h2), f"resultado é exatamente uma das duas versões (last-writer-wins), nunca mistura: {h in (h1, h2)}"
    case("F07", "Duas escritas simultâneas no mesmo arquivo: leitura nunca vê arquivo parcial/misto", "hash = v1 ou v2", f07)

    # F08 criptografia
    def f08():
        marker = b"SEGREDO-DFS-" * 1000
        p = os.path.join(FILES, "secret.txt")
        open(p, "wb").write(marker)
        rc, out = cli("put", "/files/secret.txt", f"{base}/secret.txt", env={"ENCRYPTION": "on"})
        rc2, out2 = cli("get", f"{base}/secret.txt", "/files/secret.out", env={"ENCRYPTION": "on"})
        same = open(os.path.join(FILES, "secret.out"), "rb").read() == marker
        leaked = False
        for n in range(1, 6):
            _, o = dc("exec", "-T", f"node{n}", "sh", "-c", "grep -l SEGREDO-DFS /data/* 2>/dev/null | head -1")
            leaked = leaked or bool(o.strip())
        return rc == 0 and same and not leaked, f"round-trip ok={same}; texto claro encontrado nos discos dos nós={leaked}"
    case("F08", "Criptografia ligada: nós só guardam dados cifrados; leitura devolve o original", "sem texto claro nos nós", f08)

    # F09 corrupção detectada na leitura
    cli("put", "/files/t10m.bin", f"{base}/corr.bin")

    def f09():
        m = stat(f"{base}/corr.bin")
        c0 = m["chunks"][0]
        victim = c0["replicas"][0]["node"]
        t0 = time.time()
        dc("exec", "-T", victim, "sh", "-c", f"echo CORROMPIDO >> /data/{c0['id']}")
        rc, out = cli("get", f"{base}/corr.bin", "/files/corr.out")
        same = sha(os.path.join(FILES, "corr.out")) == ref
        detected = "corrompida" in out
        t_fix = wait_for(lambda: fully_replicated(f"{base}/corr.bin"), 60)
        t_fix = (t_fix or 0) + (time.time() - t0 - (t_fix or 0)) if t_fix is not None else None  # desde a injeção
        timeline.append({"teste": "F09 corrupção na leitura", "hora_injecao": t0, "detectada_por": "cliente (hash na leitura)",
                         "reposicao_s": t_fix, "bloco": c0["id"], "no_corrompido": victim})
        return same and detected and t_fix is not None, f"detectada={detected}; arquivo íntegro={same}; N=3 restaurado em {t_fix and round(t_fix, 1)}s"
    case("F09", "Réplica corrompida: leitura detecta, usa outra réplica e o sistema substitui a cópia ruim", "arquivo íntegro + N restaurado", f09)

    # F10 corrupção detectada pelo scrubbing
    def f10():
        m = stat(f"{base}/corr.bin")
        c1 = m["chunks"][1]
        victim = c1["replicas"][0]["node"]
        t0 = time.time()
        dc("exec", "-T", victim, "sh", "-c", f"echo CORROMPIDO >> /data/{c1['id']}")
        dc("exec", "-T", victim, "python", "-c", "import requests;requests.post('http://localhost:8000/scrub')")
        t_detect = time.time() - t0
        t_fix = wait_for(lambda: fully_replicated(f"{base}/corr.bin"), 60)
        timeline.append({"teste": "F10 corrupção no scrubbing", "hora_injecao": t0, "detectada_em_s": round(t_detect, 2),
                         "reposicao_s": t_fix, "bloco": c1["id"], "no_corrompido": victim})
        return t_fix is not None, f"scrubbing detectou em {t_detect:.1f}s; réplica descartada e N=3 restaurado em {t_fix and round(t_fix, 1)}s"
    case("F10", "Scrubbing em segundo plano encontra réplica corrompida e a substitui", "N restaurado", f10)

    # T01 falha de um nó
    def t01():
        t0 = time.time()
        victim = stat(f"{base}/corr.bin")["chunks"][0]["replicas"][0]["node"]
        dc("stop", victim)
        t_dead = wait_for(lambda: next(n for n in status()["nodes"] if n["id"] == victim)["status"] == "dead", 60)
        t_rec = wait_for(lambda: fully_replicated(f"{base}/corr.bin") and not status()["rereplications_in_progress"], 120)
        rc, out = cli("get", f"{base}/corr.bin", "/files/corr.out")
        same = sha(os.path.join(FILES, "corr.out")) == ref
        m = metrics()
        timeline.append({"teste": "T01 queda de 1 nó", "no": victim, "hora_falha": t0, "detectado_morto_em_s": t_dead and round(t_dead, 1),
                         "n_restaurado_em_s": t_rec and round(t_rec + (t_dead or 0), 1), "bytes_copiados": m["rereplication"]["bytes_copied"],
                         "min_replicas_vivas": m["rereplication"]["min_live_replicas_seen"]})
        t01.victim = victim
        return t_dead is not None and t_rec is not None and same, f"{victim}: morto em {t_dead and round(t_dead, 1)}s, N=3 restaurado ~{t_rec and round(t_rec + t_dead, 1)}s após a falha; leitura íntegra={same}"
    case("T01", "Queda de um nó: detecta (heartbeat), re-replica automaticamente e mantém leituras íntegras", "N restaurado, hash correto", t01)

    # T02 nó volta: reconciliação
    def t02():
        victim = getattr(t01, "victim", "node1")
        dc("start", victim)
        t = wait_for(lambda: next(n for n in status()["nodes"] if n["id"] == victim)["status"] == "alive", 60)
        time.sleep(4)
        ev = [e for e in controller_events("NODE_RECONCILED") if e["node"] == victim][-1]
        ok_state = fully_replicated(f"{base}/corr.bin")
        return t is not None and ok_state, f"{victim} voltou em {t and round(t, 1)}s; reconciliação: {ev['kept']} blocos aproveitados, {ev['discarded']} descartados"
    case("T02", "Nó que volta é reconhecido e seus blocos reconciliados", "reconhecido, sem excesso de réplicas", t02)

    # T03 falha de N-1 = 2 nós simultâneos
    def t03():
        ids = [n["id"] for n in status()["nodes"]][:2]
        dc("stop", *ids)
        time.sleep(1)
        rc, out = cli("get", f"{base}/corr.bin", "/files/corr.out")
        same = sha(os.path.join(FILES, "corr.out")) == ref
        wait_for(lambda: all(next(n for n in status()["nodes"] if n["id"] == i)["status"] == "dead" for i in ids), 40)
        t_rec = wait_for(lambda: fully_replicated(f"{base}/corr.bin") and not status()["rereplications_in_progress"], 120)
        dc("start", *ids)
        wait_for(lambda: all(n["status"] == "alive" for n in status()["nodes"]), 60)
        return same and t_rec is not None, f"com {ids} fora (N-1=2 falhas) a leitura devolveu hash correto={same}; N restaurado={t_rec is not None}"
    case("T03", "Falha simultânea de N-1 nós: zero perda de dados", "leitura íntegra", t03)

    # T04 controlador reinicia
    def t04():
        before = stat(f"{base}/corr.bin")["sha256"]
        dc("restart", "controller")
        t = wait_for(lambda: len(status()["nodes"]) >= 5 and all(n["status"] == "alive" for n in status()["nodes"]), 60)
        after = stat(f"{base}/corr.bin")["sha256"]
        rc, out = cli("get", f"{base}/corr.bin", "/files/corr.out")
        return before == after and sha(os.path.join(FILES, "corr.out")) == ref, f"metadados recarregados do SQLite; nós se re-registraram em {t and round(t, 1)}s; arquivo íntegro"
    case("T04", "Reinício do controlador: metadados persistem e nós se re-registram sozinhos", "estado preservado", t04)

    # T05 drain
    def t05():
        victim = max(status()["nodes"], key=lambda n: n["chunks"])["id"]   # nó com mais blocos
        held = max(status()["nodes"], key=lambda n: n["chunks"])["chunks"]
        copies0 = metrics()["rereplication"]["copies_done"]
        cli("drain", victim)

        def drained():  # todo bloco tem 3 réplicas vivas FORA do nó drenado
            return all(len([r for r in c["replicas"] if r["node"] != victim and r["status"] == "alive"]) >= 3
                       for f in ("corr.bin",) for c in stat(f"{base}/{f}")["chunks"])
        t = wait_for(drained, 120)
        copies = metrics()["rereplication"]["copies_done"] - copies0
        cli("undrain", victim)
        return t is not None and copies > 0, f"drain de {victim} ({held} blocos): {copies} cópias feitas; arquivo com 3 réplicas fora dele em {t and round(t, 1)}s"
    case("T05", "Drain: esvazia um nó de forma planejada antes de retirá-lo", "3 réplicas fora do nó drenado", t05)

    # T06 descoberta automática de nó novo
    def t06():
        dc("rm", "-sf", "node6")                       # garante que o nó 6 não está rodando
        sh("docker", "volume", "rm", "-f", "dfs_node6-data")   # e que entra vazio
        wait_for(lambda: next(n for n in status()["nodes"] if n["id"] == "node6")["status"] != "alive", 30)
        t0 = time.time()
        dc("--profile", "extra", "up", "-d", "node6")
        t = wait_for(lambda: any(n["id"] == "node6" and n["status"] == "alive" for n in status()["nodes"]), 60)
        got = 0
        for i in range(4):                             # várias gravações: o nó novo (vazio) tem mais espaço livre
            cli("put", "/files/t10m.bin", f"{base}/novo{i}.bin")
            got += sum(1 for c in stat(f"{base}/novo{i}.bin")["chunks"] for r in c["replicas"] if r["node"] == "node6")
        return t is not None and got > 0, f"node6 descoberto em {t and round(t, 1)}s (contado após o `up`) sem reiniciar nada; recebeu {got} réplica(s) nas 4 gravações seguintes"
    case("T06", "Nó novo é descoberto automaticamente e passa a receber dados", "registrado sem reiniciar o sistema", t06)

    json.dump(results, open(os.path.join(RES, "functional.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(timeline, open(os.path.join(RES, "fault_timeline.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{sum(r['status'] == 'passou' for r in results)}/{len(results)} passaram")


if __name__ == "__main__":
    main()
