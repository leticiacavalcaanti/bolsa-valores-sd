"""Teste de falha controlada: derruba o market-service sob carga e mede detecção/recuperação.
Uso (na raiz do repo): python tests/part2/faults.py [servico=market-service] [downtime_s=15]
Passos: (1) grava estado de referência (ordens abertas + carteira); (2) carga contínua de leitura;
(3) docker compose stop; (4) docker compose start; (5) compara estado, mede tempo até 200 em /health.
Saída: results/fault_<servico>.json com linha do tempo e série temporal por segundo."""
import json
import subprocess
import sys
import threading
import time
import os
from common import RES, MARKET, AUTH, call, new_user, now

SVC = sys.argv[1] if len(sys.argv) > 1 else "market-service"
DOWN = float(sys.argv[2]) if len(sys.argv) > 2 else 15
URL = {"market-service": f"{MARKET}/health", "auth-service": f"{AUTH}/health"}[SVC] if SVC in ("market-service", "auth-service") else f"{MARKET}/health"


def main():
    _, tok = new_user("fl")
    _, o, _ = call("POST", f"{MARKET}/orders", {"symbol": "SERT3", "side": "BUY", "price": "0.05", "quantity": 7}, tok)
    oid = o["order"]["id"]
    _, before, _ = call("GET", f"{MARKET}/portfolio", token=tok)
    series, stop = [], threading.Event()
    t_start = time.time()

    def load():
        while not stop.is_set():
            s, _, ms = call("GET", f"{MARKET}/portfolio", token=tok, timeout=3)
            series.append({"t": round(time.time() - t_start, 2), "status": s, "ms": round(ms, 1)})
            time.sleep(0.1)
    th = threading.Thread(target=load); th.start()
    time.sleep(5)
    t_fail = time.time() - t_start
    print(now(), "injetando falha:", SVC)
    subprocess.run(["docker", "compose", "stop", SVC], check=True)
    t_det = None
    while t_det is None and time.time() - t_start < t_fail + 30:
        if call("GET", URL, timeout=2)[0] == 0:
            t_det = time.time() - t_start
        time.sleep(0.2)
    time.sleep(DOWN)
    t_restart = time.time() - t_start
    subprocess.run(["docker", "compose", "start", SVC], check=True)
    t_rec = None
    while time.time() - t_start < t_restart + 120:
        if call("GET", URL, timeout=2)[0] == 200:
            t_rec = time.time() - t_start; break
        time.sleep(0.2)
    time.sleep(5)
    stop.set(); th.join()
    _, after, _ = call("GET", f"{MARKET}/portfolio", token=tok)
    s_o, o2, _ = call("GET", f"{MARKET}/orders/{oid}", token=tok)
    tot = len(series); ok = sum(1 for x in series if x["status"] == 200)
    out = {"servico": SVC, "falha_em_s": round(t_fail, 2), "detectada_em_s": t_det, "restart_em_s": round(t_restart, 2),
           "recuperado_em_s": t_rec, "tempo_recuperacao_s": round(t_rec - t_restart, 2) if t_rec else None,
           "disponibilidade_pct": round(100 * ok / tot, 1), "requisicoes": tot,
           "estado_preservado": before.get("available") == after.get("available") and s_o == 200 and o2.get("status") in ("OPEN", "PARTIAL"),
           "carteira_antes": before.get("available"), "carteira_depois": after.get("available"), "serie": series}
    json.dump(out, open(os.path.join(RES, f"fault_{SVC}.json"), "w"), indent=1)
    print({k: v for k, v in out.items() if k != "serie"})


if __name__ == "__main__":
    main()
