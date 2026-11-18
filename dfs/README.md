# DFS — Sistema Distribuído de Armazenamento de Arquivos

Atividade 01 U2 de Sistemas Distribuídos (UFS, COMP0470). Arquivos são divididos em blocos, gravados em **N nós
distintos**, verificados por **SHA-256** (escrita, leitura e scrubbing) e **re-replicados automaticamente** quando um
nó falha. Inspirado em GFS/HDFS: um controlador cuida só de metadados e o conteúdo trafega direto entre cliente e nós.

```
                 metadados (REST/JSON)                       dados (HTTP, direto)
  cliente CLI ───────────────────────► controlador + metadados      cliente ─────► nó 1..5 (cada nó = 1 disco)
   (divide, hash, cifra)  ◄─────────── (SQLite, heartbeats,          ▲   ▲
                                        posicionamento, re-replicação)│   └── nó ◄──► nó (cópia a pedido do controlador)
                                        ▲ heartbeat/registro ─────────┘
```

| Papel | Processo | Responsabilidade |
|---|---|---|
| Controlador **e** nó de metadados (acumulados) | `dfs/controller.py` | heartbeats, descoberta, posicionamento, re-replicação, locks/commit, árvore de diretórios, mapa arquivo→blocos→réplicas (SQLite) |
| Nó de armazenamento | `dfs/node.py` (×5, +1 opcional) | guarda/serve blocos, verifica hash, heartbeat com espaço, copia blocos, scrubbing |
| Cliente | `dfs/client.py` | CLI: divide em blocos, hash, (opcional) AES-256-GCM, envio paralelo direto aos nós |

## Como executar

Requisitos: Docker e Docker Compose.

```bash
cd dfs
docker compose up -d --build            # 1 controlador + 5 nós de armazenamento
docker compose run --rm client status   # nós vivos, uso de disco, arquivos por estado
```

No Git Bash (Windows) use `export MSYS_NO_PATHCONV=1` antes, para os caminhos `/files/...` não serem convertidos.
Os arquivos locais do cliente ficam na pasta `dfs/files/` (montada como `/files` no contêiner).

## Comandos (todos com exemplo)

```bash
C="docker compose run --rm client"
$C mkdir /docs                         # criar diretório
$C put /files/a.bin /docs/a.bin        # enviar (put); --replicas N define N para este arquivo
$C put /files/a.bin /docs/b.bin --replicas 2
$C get /docs/a.bin /files/a.out        # baixar (verifica hash de cada bloco e do arquivo)
$C ls /docs                            # listar diretório (mostra o estado de cada arquivo)
$C stat /docs/a.bin                    # metadados: tamanho, data, hash, nº e localização das réplicas, estado
$C mv /docs/a.bin /docs/c.bin          # renomear/mover
$C rm /docs/c.bin                      # remover arquivo
$C rmdir /docs                         # remover diretório (só se vazio)
$C status                              # RF11: nós (vivo/suspeito/morto), espaço, arquivos por estado, re-replicações
$C metrics                             # RF12/observabilidade: JSON (também em http://localhost:9000/metrics)
$C drain node3                         # esvaziar um nó de forma planejada antes de retirá-lo
$C undrain node3
```

Estados de arquivo: **íntegro** (todos os blocos com N réplicas vivas), **sub-replicado**, **em recuperação**
(cópia em andamento), **perdido** (algum bloco sem réplica viva).

Nó novo, sem reiniciar nada e sem editar configuração: `docker compose --profile extra up -d node6`.

## Configuração (variáveis de ambiente / `.env`, sem recompilar)

| Variável | Padrão | Descrição |
|---|---|---|
| `ENCRYPTION` (cliente) | `off` | `on` liga AES-256-GCM no cliente (**obrigatório da atividade**) |
| `REPLICATION` | `3` | nível de replicação N (também por arquivo: `put --replicas`) (**obrigatório**) |
| `WRITE_QUORUM` | `2` | W: réplicas confirmadas (hash verificado) antes de responder ao cliente |
| `CHUNK_MB` | `4` | tamanho do bloco |
| `HEARTBEAT_INTERVAL_S` / `HEARTBEAT_SUSPECT_S` / `HEARTBEAT_DEAD_S` | `2` / `6` / `12` | intervalo e timeouts de suspeito/morto |
| `SCRUB_INTERVAL_S` | `30` | scrubbing em segundo plano (nós) |
| `DISK_LIMIT` | `0.9` | disco acima disso não recebe novas réplicas |
| `MAX_REREPL` | `4` | cópias de re-replicação simultâneas |
| `REPLICATION_MBPS` | `0` (sem limite) | banda máxima de cada cópia de re-replicação |
| `ALLOW_UNDER_REPLICATED` | `true` | política com poucos nós: `true` aceita "sub-replicada" e avisa; `false` rejeita |
| `NODE_CAPACITY_MB` | `500` | capacidade simulada de cada disco |

Exemplo: `REPLICATION=2 ENCRYPTION=on docker compose up -d`.

## Decisões de projeto (resumo; detalhes em [docs/relatorio-tecnico.md](docs/relatorio-tecnico.md))

- **Consistência:** forte nos metadados (um controlador, escrita em duas fases com *commit* atômico). **Quórum de escrita W=2 de N=3:**
  o cliente recebe a confirmação depois de 2 réplicas gravadas e verificadas; a 3ª completa em segundo plano.
- **Concorrência:** escritas concorrentes no mesmo caminho = *last-writer-wins* pelo commit; leitores veem a versão antiga **inteira** ou a nova
  **inteira**, nunca um arquivo parcial (o arquivo só aparece no commit).
- **Criptografia:** no **cliente**, AES-256-GCM; a chave só existe no cliente; o hash dos blocos é sobre o conteúdo **cifrado** (nós verificam sem chave).
- **Regra de não repetição:** nunca 2 réplicas no mesmo disco (nó); havendo máquinas suficientes, nunca na mesma máquina; com menos máquinas
  que N usa discos diferentes da mesma máquina e avisa; com menos nós que N aplica a política (`ALLOW_UNDER_REPLICATED`).

## Testes

```bash
python tests/functional.py                   # funcionais + falhas (F01..F10, T01..T06), grava tests/results/*.json
docker compose run --rm -T --entrypoint python client /tests/perf.py e2   # e3 | e5 | e6
python tests/recovery.py e7                  # e8 | e9
python tests/plots.py                        # gráficos .png
```

Relatório de testes: [docs/relatorio-testes.md](docs/relatorio-testes.md). Dados brutos: `tests/results/`.

## Estrutura

```
dfs/controller.py  node.py  client.py  common.py     código
docker-compose.yml                                    1 controlador + 5 nós (+ nó 6 opcional) + cliente
tests/                                                functional.py, perf.py, recovery.py, plots.py, results/
docs/                                                 relatorio-tecnico.md, relatorio-testes.md
```
