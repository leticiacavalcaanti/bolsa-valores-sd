"""Gráficos da Parte 2 da Bolsa: carga (lock global x lock por ativo) e série temporal das falhas.
Uso (na raiz): python tests/part2/plots.py -> tests/part2/results/*.png"""
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
BLUE, ORANGE, RED, GREEN, GRAY = "#2a6fbb", "#d9822b", "#c0392b", "#2e8b57", "#8a8f98"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": .25, "figure.dpi": 130})


def load(n):
    p = os.path.join(R, n)
    return json.load(open(p)) if os.path.exists(p) else None


old, new = load("load_summary_lock_global.json"), load("load_summary.json")
if new:
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.5, 3.8))
    for data, col, lab in ((old, GRAY, "lock global"), (new, BLUE, "lock por ativo")):
        if not data:
            continue
        xs = [int(k) for k in data]
        a.errorbar(xs, [v["ops_s"][0] for v in data.values()], yerr=[v["ops_s"][1] for v in data.values()], marker="o", color=col, capsize=3, label=lab)
        b.errorbar(xs, [v["p95_ms"][0] for v in data.values()], yerr=[v["p95_ms"][1] for v in data.values()], marker="o", color=col, capsize=3, label=lab)
    a.set_xlabel("usuários simultâneos"); a.set_ylabel("ordens/s"); a.set_title("Vazão (média ± IC 95%, 3 repetições)"); a.legend()
    b.set_xlabel("usuários simultâneos"); b.set_ylabel("latência p95 (ms)"); b.set_title("Latência p95"); b.legend()
    fig.tight_layout(); fig.savefig(os.path.join(R, "carga.png")); plt.close(fig); print("carga.png")

for svc in ("market-service", "auth-service"):
    d = load(f"fault_{svc}.json")
    if not d:
        continue
    s = d["serie"]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.scatter([x["t"] for x in s if x["status"] == 200], [x["ms"] for x in s if x["status"] == 200], s=8, color=BLUE, label="sucesso")
    ax.scatter([x["t"] for x in s if x["status"] != 200], [0 for x in s if x["status"] != 200], s=14, color=RED, marker="x", label="falha (sem resposta)")
    for key, lab, col in (("falha_em_s", "falha injetada", RED), ("detectada_em_s", "detectada", ORANGE), ("restart_em_s", "restart", GRAY), ("recuperado_em_s", "recuperado", GREEN)):
        if d.get(key):
            ax.axvline(d[key], color=col, linestyle="--", lw=1); ax.text(d[key] + .2, ax.get_ylim()[1] * .9, lab, rotation=90, va="top", fontsize=8, color=col)
    ax.set_xlabel("tempo (s)"); ax.set_ylabel("latência de GET /portfolio (ms)"); ax.set_title(f"Falha de {svc} sob carga de leitura"); ax.legend(loc="upper center")
    fig.tight_layout(); fig.savefig(os.path.join(R, f"falha_{svc}.png")); plt.close(fig); print(f"falha_{svc}.png")
