"""Gera os gráficos do relatório a partir de tests/results/*.json  ->  tests/results/*.png
Barras de erro = intervalo de confiança de 95%. Uso (em dfs/): python tests/plots.py
"""
import json
import os
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
BLUE, ORANGE, GRAY, RED, GREEN = "#2a6fbb", "#d9822b", "#8a8f98", "#c0392b", "#2e8b57"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25,
                     "font.size": 10, "figure.dpi": 130})


def load(name):
    p = os.path.join(RES, name)
    return json.load(open(p)) if os.path.exists(p) else None


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(RES, name))
    plt.close(fig)
    print("gerado", name)


def line_ci(ax, xs, rows, key, color, label):
    ys = [r[key][0] for r in rows]
    es = [r[key][1] for r in rows]
    ax.errorbar(xs, ys, yerr=es, marker="o", color=color, capsize=3, label=label)


def e2():
    d = load("E2_clientes.json")
    if not d:
        return
    xs = [r["config"] for r in d]
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.6))
    line_ci(a, xs, d, "ops_s", BLUE, "operações/s")
    a.set_xlabel("clientes simultâneos"); a.set_ylabel("operações/s (put+get de 1 MB)"); a.set_title("Vazão")
    line_ci(b, xs, d, "p50", BLUE, "p50"); line_ci(b, xs, d, "p95", ORANGE, "p95")
    b.set_xlabel("clientes simultâneos"); b.set_ylabel("latência (ms)"); b.set_title("Latência"); b.legend()
    for ax in (a, b):
        ax.set_xscale("log", base=2); ax.set_xticks(xs); ax.set_xticklabels(xs)
    save(fig, "E2_clientes.png")


def e3():
    d = load("E3_tamanho.json")
    if not d:
        return
    names = [r["config"][0] for r in d]
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.6))
    a.bar(names, [r["ops_s"][0] for r in d], yerr=[r["ops_s"][1] for r in d], color=BLUE, capsize=3)
    a.set_ylabel("operações/s"); a.set_title("Operações por segundo (metadados dominam em arquivos pequenos)")
    a.title.set_fontsize(9)
    b.bar(names, [r["mb_s"][0] for r in d], yerr=[r["mb_s"][1] for r in d], color=ORANGE, capsize=3)
    b.set_ylabel("vazão (MB/s)"); b.set_title("Vazão de dados (rede/disco dominam em arquivos grandes)")
    b.title.set_fontsize(9)
    for ax in (a, b):
        ax.set_xlabel("tamanho do arquivo")
    save(fig, "E3_tamanho.png")


def e5():
    d = load("E5_replicacao.json")
    if not d:
        return
    xs = [r["config"] for r in d]
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(12, 3.6))
    line_ci(a, xs, d, "write_mb_s", BLUE, "escrita"); line_ci(a, xs, d, "read_mb_s", ORANGE, "leitura")
    a.set_xlabel("nível de replicação N"); a.set_ylabel("vazão (MB/s)"); a.set_title("Vazão"); a.legend()
    line_ci(b, xs, d, "write_ms", BLUE, "escrita"); line_ci(b, xs, d, "read_ms", ORANGE, "leitura")
    b.set_xlabel("nível de replicação N"); b.set_ylabel("tempo (ms) para 10 MB"); b.set_title("Tempo"); b.legend()
    line_ci(c, xs, d, "overhead_x", GREEN, "medido"); c.plot(xs, xs, "--", color=GRAY, label="esperado = N")
    c.set_xlabel("nível de replicação N"); c.set_ylabel("espaço gravado / dado original (×)"); c.set_title("Sobrecarga de espaço"); c.legend()
    for ax in (a, b, c):
        ax.set_xticks(xs)
    save(fig, "E5_replicacao.png")


def e6():
    d = load("E6_cripto.json")
    if not d:
        return
    names = [r["config"] for r in d]
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.6))
    w = 0.35
    for i, (k, lab, col) in enumerate((("write_mb_s", "escrita", BLUE), ("read_mb_s", "leitura", ORANGE))):
        a.bar([x + (i - 0.5) * w for x in range(len(d))], [r[k][0] for r in d], w, yerr=[r[k][1] for r in d], color=col, capsize=3, label=lab)
    a.set_xticks(range(len(d))); a.set_xticklabels([f"cifra {n}" for n in names]); a.set_ylabel("vazão (MB/s)"); a.legend()
    a.set_title("Vazão com e sem criptografia")
    b.bar(names, [r["cpu_s_per_mb"][0] for r in d], yerr=[r["cpu_s_per_mb"][1] for r in d], color=GRAY, capsize=3)
    b.set_ylabel("CPU do cliente (s por MB)"); b.set_title("Uso de CPU")
    save(fig, "E6_cripto.png")


def e7():
    d = load("E7_recuperacao.json")
    if not d:
        return
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.5, 3.6))
    for tag, col, lab in (("banda_livre", BLUE, "sem limite de banda"), ("limite_8MBps", ORANGE, "limite 8 MB/s por cópia")):
        rows = [r for r in d if r["tag"] == tag]
        vols = sorted({r["volume_mb"] for r in rows})
        ys, es, bs = [], [], []
        for v in vols:
            t = [r["recuperado_s"] for r in rows if r["volume_mb"] == v]
            ys.append(statistics.mean(t)); es.append(2.78 * statistics.stdev(t) / len(t) ** 0.5 if len(t) > 2 else 0)
            bs.append(statistics.mean(r["vazao_rereplicacao_mb_s"] for r in rows if r["volume_mb"] == v))
        a.errorbar(vols, ys, yerr=es, marker="o", color=col, capsize=3, label=lab)
        b.plot(vols, bs, marker="o", color=col, label=lab)
    a.set_xlabel("volume armazenado (MB)"); a.set_ylabel("tempo até N réplicas (s)"); a.set_title("Tempo de recuperação"); a.legend()
    b.set_xlabel("volume armazenado (MB)"); b.set_ylabel("vazão de re-replicação (MB/s)"); b.set_title("Vazão da re-replicação")
    save(fig, "E7_recuperacao.png")


def timeline(name, ev_file, tl_file, markers):
    ev, tl = load(ev_file), load(tl_file)
    if not ev or not tl:
        return
    t0 = min(e["t"] for e in ev)
    n = int(max(e["t"] for e in ev) - t0) + 1
    thr, lat, err = [0] * n, [[] for _ in range(n)], [0] * n
    for e in ev:
        s = int(e["t"] - t0)
        if e["ok"]:
            thr[s] += 1
            lat[s].append(e["ms"])
        else:
            err[s] += 1
    p95 = [sorted(l)[int(len(l) * 0.95)] if l else None for l in lat]
    fig, (a, b) = plt.subplots(2, 1, figsize=(9, 5.2), sharex=True)
    a.plot(range(n), thr, color=BLUE, label="operações com sucesso/s")
    a.plot(range(n), err, color=RED, label="operações com erro/s")
    a.set_ylabel("operações/s"); a.legend(loc="lower left")
    b.plot([i for i, v in enumerate(p95) if v is not None], [v for v in p95 if v is not None], color=ORANGE)
    b.set_ylabel("latência p95 (ms)"); b.set_xlabel("tempo (s)")
    for key, label, col in markers:
        if tl.get(key):
            x = tl[key] - t0
            for ax in (a, b):
                ax.axvline(x, color=col, linestyle="--", linewidth=1)
            a.text(x + 0.3, a.get_ylim()[1] * 0.92, label, color=col, fontsize=8, rotation=90, va="top")
    save(fig, name)


def main():
    e2(); e3(); e5(); e6(); e7()
    timeline("E9_falha.png", "E9_events.json", "E9_timeline.json",
             [("hora_falha", "falha injetada", RED), ("hora_detectado", "detectada (nó morto)", ORANGE),
              ("hora_recuperado", "N réplicas restauradas", GREEN), ("hora_no_volta", "nó volta", GRAY)])
    timeline("E8_no_novo.png", "E8_events.json", "E8_no_novo.json", [("hora_entrada", "nó 6 entra", BLUE)])


if __name__ == "__main__":
    main()
