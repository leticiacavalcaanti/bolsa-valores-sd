"""Gera dfs/docs/relatorio-testes.md a partir de tests/results/*. Uso (em dfs/): python tests/report.py"""
import json
import os
import statistics
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
OUT = os.path.join(os.path.dirname(HERE), "docs", "relatorio-testes.md")


def load(n):
    p = os.path.join(R, n)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def sh(c):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, cwd=os.path.dirname(HERE)).stdout.strip()
    except Exception:
        return "?"


def ci(x, d=2):
    return f"{x[0]:.{d}f} ± {x[1]:.{d}f}"


fn, tl = load("functional.json"), load("fault_timeline.json")
e2, e3, e5, e6 = (load(f"{n}.json") for n in ("E2_clientes", "E3_tamanho", "E5_replicacao", "E6_cripto"))
e7, e8 = load("E7_recuperacao.json"), load("E8_no_novo.json")
e9 = load("E9_timeline.json")

o = ["# Relatório de testes — DFS\n",
     "## 1. Ambiente e versão testada\n",
     f"- Versão testada (tag Git): `{sh('git describe --tags --always')}`",
     f"- Software: {sh('docker --version')}; Python 3.12 (imagem `python:3.12-slim`); FastAPI/uvicorn; SQLite; `cryptography` (AES-GCM).",
     "- Topologia: **1 controlador (+ metadados) e 5 nós de armazenamento** (6º nó para os testes de entrada de nós), cada nó com seu volume Docker; "
     "disco simulado de 500 MB por nó (`NODE_CAPACITY_MB`). Cliente e gerador de carga rodam em contêiner na mesma rede.",
     "- **Todos os contêineres compartilham uma única máquina física** (Docker Desktop, 5,8 GiB de RAM para o Docker): CPU, memória e disco são disputados "
     "entre controlador, nós e clientes, e a rede é a rede virtual do Docker (latência desprezível, sem limite de banda real). "
     "Isso favorece a vazão absoluta e **não representa uma rede real**; só as comparações relativas entre configurações são confiáveis.",
     "- *Preencher:* CPU (modelo/núcleos), RAM total, tipo de disco, `iperf3`/`ping` entre contêineres.",
     "- Repetições: 4 por configuração (a 1ª, de aquecimento, é descartada ⇒ 3 válidas); média ± intervalo de confiança de 95% (t de Student).\n",
     "## 2. Testes funcionais e de integridade\n", "| ID | Objetivo | Esperado | Obtido | Status |", "|---|---|---|---|---|"]
if fn:
    o += [f"| {t['id']} | {t['objetivo']} | {t['esperado']} | {str(t['obtido'])[:230]} | {t['status']} |" for t in fn]
    o.append(f"\nResumo: **{sum(t['status'] == 'passou' for t in fn)}/{len(fn)}** passaram. Evidências: `tests/results/functional.json`, logs dos contêineres "
             "(`docker compose logs`). Reexecutável: `python tests/functional.py`.\n")

o += ["## 3. Tolerância a falhas\n",
      "Procedimento de cada teste: (1) gravar arquivos e guardar os hashes de referência; (2) injetar a falha anotando a hora; (3) observar detecção, "
      "re-replicação e estado final; (4) baixar e comparar o SHA-256.\n"]
if tl:
    o += ["| Teste | Resultado medido |", "|---|---|"]
    for t in tl:
        o.append(f"| {t['teste']} | " + "; ".join(f"{k}={v if not isinstance(v, float) else round(v, 2)}" for k, v in t.items() if k != "teste" and k != "hora_injecao" and k != "hora_falha") + " |")
    o.append("")
o += ["**Janela de vulnerabilidade e custo da recuperação:** ver E7/E9 abaixo. O tempo de detecção (~10–11 s) é dominado pelo timeout de heartbeat "
      "(`HEARTBEAT_DEAD_S=12`), um parâmetro configurável: reduzi-lo detecta mais rápido, ao custo de mais falsos positivos.\n",
      "Critérios de sucesso: zero perda enquanto falhas simultâneas < N (T03 derrubou N−1=2 nós e todos os arquivos foram lidos com hash correto); "
      "todo arquivo lido tem hash correto (F02, F09, T01–T04); nível de replicação restaurado automaticamente (T01, F09, F10); o sistema não entrega dado corrompido (F09).\n",
      "## 4. Escalabilidade e desempenho\n"]


def table(title, rows, cols, labels, cfg=lambda c: c):
    t = [f"### {title}\n", "| Configuração | " + " | ".join(labels) + " |", "|---|" + "---|" * len(cols)]
    for r in rows:
        t.append(f"| {cfg(r['config'])} | " + " | ".join(ci(r[c], 1 if c in ('p50', 'p95', 'write_ms', 'read_ms') else 2) for c in cols) + " |")
    return t + [""]


if e2:
    o += table("E2 — mais clientes simultâneos (put+get de 1 MB, 5 nós, N=3)", e2, ["ops_s", "mb_s", "p50", "p95"],
               ["operações/s", "MB/s agregados", "latência p50 (ms)", "latência p95 (ms)"], lambda c: f"{c} cliente(s)")
    o += ["![E2](../tests/results/E2_clientes.png)\n"]
if e3:
    o += table("E3 — tamanho dos arquivos (4 clientes)", e3, ["ops_s", "mb_s", "p50", "p95"],
               ["operações/s", "MB/s agregados", "p50 (ms)", "p95 (ms)"], lambda c: c[0])
    o += ["![E3](../tests/results/E3_tamanho.png)\n"]
if e5:
    o += table("E5 — custo da replicação (arquivo de 10 MB)", e5, ["write_ms", "write_mb_s", "read_ms", "read_mb_s", "overhead_x"],
               ["escrita (ms)", "escrita (MB/s)", "leitura (ms)", "leitura (MB/s)", "espaço gravado / original (×)"], lambda c: f"N={c}")
    o += ["![E5](../tests/results/E5_replicacao.png)\n"]
if e6:
    o += table("E6 — custo da criptografia (arquivo de 20 MB; CPU = tempo de processo do cliente)", e6, ["write_mb_s", "read_mb_s", "cpu_s_per_mb"],
               ["escrita (MB/s)", "leitura (MB/s)", "CPU do cliente (s/MB)"], lambda c: f"cifra {c}")
    o += ["![E6](../tests/results/E6_cripto.png)\n"]
if e7:
    o += ["### E7 — recuperação em escala (derruba o nó com mais blocos; N=3; 5 nós)\n",
          "| Volume | Limite de banda | Nó | Blocos no nó | Detecção (s) | Recuperado em (s) | Copiado (MB) | Vazão re-replicação (MB/s) |", "|---|---|---|---|---|---|---|---|"]
    for r in e7:
        o.append(f"| {r['volume_mb']} MB | {r['tag']} | {r['no']} | {r['blocos_no_no']} | {r['detectado_s']:.1f} | {r['recuperado_s']:.1f} | "
                 f"{r['bytes_copiados'] / 1048576:.0f} | {r['vazao_rereplicacao_mb_s']:.1f} |")
    o += ["\n![E7](../tests/results/E7_recuperacao.png)\n"]
if e8:
    o += ["### E8 — entrada de um nó novo durante a carga\n",
          f"- Nó descoberto (registrado e vivo) em **{e8['descoberto_em_s']:.1f} s** após `docker compose up node6`, sem reiniciar nada.",
          f"- Primeiro bloco recebido em **{e8['primeiro_bloco_em_s']:.1f} s**." if e8.get("primeiro_bloco_em_s") else "- O nó ainda não havia recebido blocos ao fim da janela.",
          "![E8](../tests/results/E8_no_novo.png)\n"]
if e9:
    o += ["### E9 — desempenho sob falha (carga contínua; um nó derrubado e religado)\n",
          f"- Falha injetada, detecção (+{e9['hora_detectado'] - e9['hora_falha']:.1f} s), "
          + (f"N réplicas restauradas (+{e9['hora_recuperado'] - e9['hora_falha']:.1f} s), " if e9.get("hora_recuperado") else "")
          + f"nó volta (+{e9['hora_no_volta'] - e9['hora_falha']:.1f} s). Linha do tempo no gráfico.",
          "![E9](../tests/results/E9_falha.png)\n"]

o += ["### Análise dos resultados\n",
      "- **E2 (joelho):** a vazão sobe de ~30 para ~45 operações/s até 4 clientes e **satura em ~46–47 ops/s a partir de 8 clientes**, enquanto a latência continua "
      "crescendo (p50 de 32 ms com 1 cliente para 303 ms com 16; p95 605 ms): a partir de ~4–8 clientes só aumenta a fila, sem ganho de vazão. "
      "Como controlador, nós e clientes dividem a mesma máquina, não dá para separar se o limite é o lock/CPU do controlador, a CPU da máquina ou o disco. "
      "Os ICs com 1–2 clientes são largos (poucas operações por janela de 8 s).",
      "- **E3 (tamanho):** arquivos pequenos (10–100 KB) rendem ~78 ops/s mas só 0,8–7,6 MB/s: o custo é de **metadados** (3 chamadas ao controlador por operação), "
      "a vazão em MB/s é baixa. Com 1–10 MB a vazão de dados sobe (40–69 MB/s) e o número de operações cai: passa a dominar a **transferência**. "
      "**Atenção: os resultados de 10 MB e principalmente 50 MB têm IC enorme** (poucas operações por repetição de 8 s: com 50 MB uma operação leva ~10 s), "
      "portanto só indicam a tendência; para conclusões seriam necessárias janelas maiores.",
      "- **E5 (replicação):** o espaço gravado é exatamente **N× o original (1,00; 2,00; 3,00; 4,00)**, como esperado. Os tempos de escrita têm IC muito largo "
      "(a escrita com N=2 chegou a ± 1,4 s) e **não** mostram um padrão claro de piora com N (o cliente envia aos N nós em paralelo e a rede virtual do Docker não é gargalo); "
      "a leitura não piora com N de forma significativa (lê de uma réplica).",
      "- **E6 (criptografia):** com AES-256-GCM a escrita caiu ~14% (49,5 para 42,5 MB/s) e a leitura ~30% (69,6 para 48,4 MB/s), mas **as diferenças estão dentro dos intervalos de confiança** "
      "(± 17 a 40 MB/s); o uso de CPU do cliente dobrou (0,01 para 0,02 s/MB). O hash SHA-256 é calculado nos dois casos (não variamos a etapa de hash).",
      "- **E7 (recuperação em escala):** o tempo total até restabelecer N réplicas cresce com o volume do nó perdido: **~16 s (50 MB), ~17 s (100 MB), ~22–23 s (200 MB)**; "
      "dos quais ~10–11 s são a **detecção** (timeout de heartbeat 12 s) e o restante é cópia (5 s, 7 s e 11 s para 44, 69 e 119 MB: ~8–10 MB/s). "
      "**O limite de banda de 8 MB/s por cópia praticamente não alterou o resultado** (17–17,5 s sem limite vs 19–20 s com limite para 100 MB), porque a re-replicação já corre perto desse ritmo: "
      "o fator limitante é o laço de re-replicação (varre a cada 1 s e lança até 4 cópias) e não a banda; um teste com limite bem menor (ex.: 1–2 MB/s) mostraria o efeito. "
      "Não testamos o efeito de ter mais nós ajudando na cópia (só havia 5 nós).",
      "- **E8 (nó novo):** descoberto em ~1,6 s após o `up` (limite do intervalo de heartbeat de 2 s + resolução de 0,5 s da medição) e já recebendo blocos de gravações novas "
      "na mesma janela, porque o posicionamento prefere o nó com mais espaço livre. O efeito do nó novo na latência não é distinguível no gráfico.",
      "- **E9 (desempenho sob falha):** com carga contínua de 4 clientes, **nenhuma operação falhou** durante a queda do nó (disponibilidade 100%; leituras usam outra réplica, "
      "escritas usam W=2 de N=3). O gráfico mostra uma queda breve de vazão e um pico de p95 (~900 ms) **em torno da injeção da falha**; a vazão depois não fica abaixo da do início "
      "(a carga ainda estava aquecendo nos primeiros segundos). A marcação da falha pode ter ~1–2 s de deslocamento por diferença de relógio entre o contêiner e o host.\n",
      ]
o += ["### Não realizados\n",
      "- **E1 (escalabilidade horizontal, 3/5/8/12 nós)**: só havia 5–6 nós numa máquina; sem CPU/disco adicionais os nós disputam os mesmos recursos, "
      "então o experimento não mediria escala real. **E4 (100 mil arquivos)** não executado por tempo.\n",
      "## 5. Problemas encontrados, correções e limitações\n",
      "| Problema | Causa | Correção |", "|---|---|---|",
      "| Controlador travou (CPU 100%, heartbeats expirando) na 1ª gravação | `posixpath.normpath` preserva `//` no início; `ensure_parents` entrou em laço infinito segurando o lock global | Normalização com `lstrip('/')` e laço de diretórios com condição de parada |",
      "| F01 falhou numa execução logo após `docker compose up` | A 1ª execução do contêiner cliente logo após o `up` falhou no ambiente de teste (não reproduzível isolado) | Passo de aquecimento no início do teste |",
      "| Sobrecarga de espaço negativa/ruidosa na 1ª versão do E5 | Medida via heartbeat (defasada, afetada por limpeza de blocos) | Passou a ser calculada pelos metadados: bytes × réplicas do arquivo |",
      "\n**Limitações que permanecem:** controlador único (ponto único de *disponibilidade*, sem consenso); varredura O(blocos) a cada 1 s na re-replicação; "
      "cliente carrega o arquivo inteiro em memória; só diretórios vazios removíveis e só arquivos movíveis; sem domínios de falha (rack/zona); "
      "teste do limite de uso do disco (90%) e de queda no meio de uma gravação **não** automatizados; todos os nós na mesma máquina física.\n",
      "## 6. Análise crítica\n",
      "- **Gargalos:** com 1 controlador e tudo na mesma máquina, o limite observado vem de CPU compartilhada e do lock global do controlador "
      "(cada `allocate`/`commit`/`stat` serializa); para arquivos pequenos domina o custo de metadados (3 chamadas ao controlador por operação), para grandes domina a transferência.",
      "- **Riscos:** o controlador é ponto único de disponibilidade (os dados e metadados sobrevivem a reinício, T04); o scrubbing relê todos os blocos "
      "(custo de E/S proporcional ao volume); a re-replicação rápida pode competir com os clientes (mitigada por `MAX_REREPL` e `REPLICATION_MBPS`).",
      "- **Para 10×/100×:** metadados replicados com Raft (como HDFS HA/Ceph MON), particionados por subárvore ou por hash; re-replicação orientada a eventos "
      "por nó em vez de varredura; descoberta por gossip; *erasure coding* (MinIO) para reduzir o custo de espaço de N× para ~1,4×; posicionamento "
      "por domínio de falha (CRUSH, Ceph).",
      "- **Comparação:** a arquitetura é a do GFS/HDFS (controlador/NameNode de metadados + nós/DataNodes de dados, blocos replicados, heartbeats, re-replicação); "
      "difere do Ceph (sem mapa de posicionamento determinístico, o controlador decide) e do MinIO (replicação inteira em vez de erasure coding).\n",
      "## 7. Anexos\n", "Scripts: `tests/functional.py`, `tests/perf.py`, `tests/recovery.py`, `tests/plots.py`, `tests/report.py`. "
      "Dados brutos e logs: `tests/results/` (`*.json`, `perf.log`, `E9_events.json`).\n"]
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write("\n".join(o))
print("gerado", OUT)
