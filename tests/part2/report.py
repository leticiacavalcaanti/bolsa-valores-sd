"""Gera docs/relatorio-testes.md (Bolsa, Parte 2) a partir de tests/part2/results/*.
Uso (na raiz do repo): python tests/part2/report.py"""
import json
import os
import subprocess

R = "tests/part2/results"


def sh(c):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "?"


def load(name):
    p = f"{R}/{name}"
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


f = load("functional.json")
new, old = load("load_summary.json"), load("load_summary_lock_global.json")
fmt = lambda x: f"{x[0]:.1f} ± {x[1]:.1f}"

o = ["# Relatório de testes — Simulador de Bolsa (Parte 2)\n",
     "## 1. Ambiente e versão testada\n",
     f"- Versão testada: tag Git `{sh('git describe --tags --always')}`.",
     f"- Software: {sh('docker --version')}; Python 3.12; FastAPI; PostgreSQL (imagem do compose); Next.js.",
     "- Topologia: 1 `market-service`, 1 `auth-service`, 1 `npc-service` (14 agentes), 1 PostgreSQL, 1 frontend, todos em contêineres.",
     "- **Todos os serviços, o banco e o gerador de carga rodam na MESMA máquina física** (Docker Desktop, 5,8 GiB de RAM para o Docker). "
     "Os resultados de desempenho medem a máquina inteira e **não** isolam cada componente.",
     "- *Preencher:* CPU, RAM total, tipo de disco da máquina. Rede: tráfego em `localhost`/rede virtual do Docker (latência desprezível).\n",
     "## 2. Testes funcionais\n", "| ID | Objetivo | Esperado | Obtido | Status |", "|---|---|---|---|---|"]
if f:
    o += [f"| {t['id']} | {t['objetivo']} | {t['esperado']} | {t['obtido']} | {t['status']} |" for t in f]
    o.append(f"\nResumo: {sum(t['status'] == 'passou' for t in f)}/{len(f)} passaram. Evidência: `tests/part2/results/functional.json` (reexecutável com `python tests/part2/functional.py`).\n")
o += ["### Concorrência entre ativos (invariantes)\n",
      "Após a carga com 175 usuários criados e ~2.600 negociações adicionais, consultas diretas ao banco mostraram: "
      "**0 contas com saldo negativo, 0 posições negativas, total de ativos em carteira constante (70.000)** e variação do dinheiro total "
      "igual exatamente a 175 × R$ 100.000 (saldo inicial dos usuários novos). Ou seja, dinheiro e ativos se conservam sob concorrência.\n",
      "## 3. Tolerância a falhas\n",
      "Procedimento: (1) cria uma ordem aberta e guarda a carteira de referência; (2) carga contínua de leitura (10 req/s); (3) `docker compose stop` do serviço; "
      "(4) mede detecção, espera e `start`; (5) compara carteira e ordem aberta.\n"]
for svc in ("market-service", "auth-service"):
    d = load(f"fault_{svc}.json")
    if d:
        o += [f"### Falha de `{svc}`\n",
              f"| Evento | t (s) |", "|---|---|",
              f"| Falha injetada | {d['falha_em_s']} |", f"| Falha detectada (sem resposta) | {d['detectada_em_s']:.2f} |",
              f"| `start` do serviço | {d['restart_em_s']} |", f"| Serviço de volta | {d['recuperado_em_s']:.2f} |\n",
              f"- Tempo de recuperação após o restart: **{d['tempo_recuperacao_s']} s**; disponibilidade de leitura na janela inteira: **{d['disponibilidade_pct']}%** ({d['requisicoes']} requisições).",
              f"- Estado preservado (carteira e ordem aberta idênticas): **{d['estado_preservado']}**.",
              f"![falha {svc}](../tests/part2/results/falha_{svc}.png)\n"]
o += ["Análise: a queda do `market-service` torna o mercado indisponível (as requisições falham) até o contêiner voltar, mas **nada confirmado se perde** (PostgreSQL). "
      "A queda do `auth-service` **não afeta** quem já tem sessão, pois o JWT é validado localmente no `market-service` (disponibilidade 100% no experimento); só novos logins falhariam. "
      "A detecção aqui é por falha de requisição (não há monitor de saúde dedicado) e o Docker reinicia o serviço (`restart: unless-stopped`). "
      "**Não testado:** queda do `npc-service` e do PostgreSQL; falha no meio de uma transação foi apenas argumentada (rollback automático), não injetada.\n",
      "## 4. Escalabilidade e desempenho\n",
      "Carga: N usuários simultâneos enviando ordens limitadas aleatórias perto do preço (e consultando `/assets`), 10 s por repetição, "
      "3 repetições + 1 aquecimento descartado. Resultado: média ± IC 95%.\n"]
if new:
    o += ["| Usuários | Ordens/s (lock por ativo) | p50 (ms) | p95 (ms) |" + (" Ordens/s (lock global, antes) | p95 global (ms) |" if old else ""),
          "|---|---|---|---|" + ("---|---|" if old else "")]
    for n, v in new.items():
        row = f"| {n} | {fmt(v['ops_s'])} | {fmt(v['p50_ms'])} | {fmt(v['p95_ms'])} |"
        if old:
            row += f" {fmt(old[n]['ops_s'])} | {fmt(old[n]['p95_ms'])} |"
        o.append(row)
    o += ["\n![carga](../tests/part2/results/carga.png)\n",
          "**Joelho da curva:** a vazão para de crescer em ~35–40 ordens/s a partir de 50 usuários, enquanto o p50 passa de ~170 ms (5 usuários) para ~1,8 s (100 usuários): "
          "a latência cresce com a fila sem ganho de vazão.\n",
          "**Lock global → lock por ativo:** a mudança (um lock por ativo, travamento das contas em ordem crescente de `user_id` para evitar deadlock) "
          "**não trouxe ganho mensurável** nesta máquina: as diferenças estão dentro dos intervalos de confiança (que são largos). O gargalo passou a ser outro: "
          "o PostgreSQL chegou a ~35% de CPU, existe **um único processo Python** (GIL) e o gerador de carga e os 14 agentes compartilham a mesma máquina. "
          "O ganho teórico do lock por ativo só apareceria com mais CPU/instâncias. Houve picos de latência de 4–6 s em algumas repetições (p95 com IC largo); a causa não foi investigada.\n"]
o += ["## 5. Problemas encontrados, correções e limitações\n",
      "| Problema | Causa | Correção |", "|---|---|---|",
      "| F12 falhou na primeira execução do teste | Expectativa errada do teste (esperava 5 compras aceitas; só cabiam 4 pois R$ 0,06 já estavam reservados) | Teste passou a calcular o esperado a partir do saldo disponível |",
      "| Resultados de carga não salvos | Scripts usavam caminho relativo ao diretório atual | Caminhos relativos ao arquivo do script |",
      "\n**Limitações que permanecem:** instância única do `market-service` (o lock por ativo é de processo; réplicas exigiriam travas no banco ou particionamento por ativo entre instâncias); "
      "PostgreSQL único; testes em uma só máquina; falhas de `npc-service`/PostgreSQL não testadas; sem teste de caos automatizado; picos de latência não explicados; "
      "sem monitor ativo de saúde dos serviços (apenas `/health` e `/metrics`).\n",
      "## 6. Análise crítica\n",
      "- **Gargalos:** CPU compartilhada na máquina de teste, processo Python único (GIL) e PostgreSQL; a serialização por ativo limita o *pior caso* "
      "(todos negociando o mesmo ativo ⇒ continua serial).",
      "- **Pontos únicos de falha:** `market-service`, PostgreSQL e o `auth-service` (para novos logins). O estado confirmado sobrevive a reinícios.",
      "- **Para 10× / 100×:** um engine por ativo em processos/instâncias separadas (sharding) com saldo reservado antes do casamento; réplica de leitura e "
      "pool de conexões (PgBouncer); fila de eventos (Kafka/NATS) para notificações; várias instâncias atrás de balanceador com *sticky* WebSocket; "
      "PostgreSQL com réplica/HA (Patroni) ou banco distribuído (CockroachDB).",
      "- **Observabilidade:** `GET /metrics` (JSON) no `market-service`: uptime, requisições por rota/status, latência p50/p95/p99, ordens/s, negociações e usuários online; "
      "logs JSON por ordem (`ORDER_RECEIVED → ... → CLIENTS_NOTIFIED`).\n",
      "## 7. Anexos\n",
      "Scripts em `tests/part2/` (`functional.py`, `load.py`, `faults.py`, `plots.py`, `report.py`); dados brutos em `tests/part2/results/` "
      "(`load.csv`, `load_summary*.json`, `fault_*.json`, `functional.json`, `docker_stats.csv`).\n"]
open("docs/relatorio-testes.md", "w", encoding="utf-8").write("\n".join(o))
print("docs/relatorio-testes.md gerado")
