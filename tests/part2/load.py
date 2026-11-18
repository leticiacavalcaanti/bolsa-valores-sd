"""Testes de carga (E2): usuários simultâneos 5/20/50/100, cada cenário repetido REPS vezes.
Uso: python load.py [duração_s=10] [repetições=3]
Cada usuário alterna ordens de compra/venda limitadas perto do preço e consulta de carteira.
Saída: results/load.csv (bruto por repetição) e results/load_summary.json (média ± IC95%)."""
import csv
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import os
from common import RES, MARKET, call, mean_ci, new_user, pct, now

SYMS = ["CAJU3", "ARAC3", "SERT3", "MANG3", "FORR3"]
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 10
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 3


def worker(tok, stop, lat, errs, counts):
    while time.time() < stop:
        sym = random.choice(SYMS)
        _, assets, _ = call("GET", f"{MARKET}/assets", token=tok)
        price = next((float(a["last_price"]) for a in assets if a["symbol"] == sym), 20.0) if isinstance(assets, list) else 20.0
        side = random.choice(["BUY", "SELL"])
        body = {"symbol": sym, "side": side, "price": f"{price * random.uniform(0.97, 1.03):.2f}", "quantity": random.randint(1, 5)}
        s, _, ms = call("POST", f"{MARKET}/orders", body, tok, timeout=30)
        lat.append(ms)
        counts["total"] += 1
        if s == 201:
            counts["ok"] += 1
        elif s == 422:
            counts["rejeitada_regra"] += 1  # saldo/ativo insuficiente: resposta correta, não é erro
        else:
            errs.append(s)


def run(users_tokens, dur):
    lat, errs = [], []
    counts = {"total": 0, "ok": 0, "rejeitada_regra": 0}
    stop = time.time() + dur
    t0 = time.time()
    with ThreadPoolExecutor(len(users_tokens)) as ex:
        list(ex.map(lambda t: worker(t, stop, lat, errs, counts), users_tokens))
    el = time.time() - t0
    return {"ops": counts["total"], "ops_s": counts["total"] / el, "p50": pct(lat, 50), "p95": pct(lat, 95),
            "mean": sum(lat) / len(lat) if lat else 0, "erros_infra": len(errs), "regra": counts["rejeitada_regra"]}


def main():
    rows, summary = [], {}
    for n in (5, 20, 50, 100):
        toks = [new_user("ld")[1] for _ in range(n)]
        toks = [t for t in toks if t]
        run(toks[:min(n, 5)], 3)  # aquecimento (descartado)
        ops, p95, p50 = [], [], []
        for r in range(1, REPS + 1):
            res = run(toks, DUR)
            rows.append({"usuarios": n, "rep": r, "hora": now(), **res})
            ops.append(res["ops_s"]); p95.append(res["p95"]); p50.append(res["p50"])
            print(n, r, {k: round(v, 1) if isinstance(v, float) else v for k, v in res.items()})
        summary[n] = {"ops_s": mean_ci(ops), "p50_ms": mean_ci(p50), "p95_ms": mean_ci(p95), "reps": REPS}
    with open(os.path.join(RES, "load.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    json.dump(summary, open(os.path.join(RES, "load_summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
