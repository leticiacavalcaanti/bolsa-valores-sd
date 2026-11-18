# Relatório técnico — DFS (Sistema Distribuído de Armazenamento de Arquivos)

Disciplina de Sistemas Distribuídos (UFS, COMP0470). Python 3.12, FastAPI, SQLite, Docker Compose.

## 1. Arquitetura e papéis

```
 ┌────────────┐  1 allocate/commit/stat/ls (REST JSON)   ┌──────────────────────────────┐
 │  Cliente   │ ───────────────────────────────────────► │ Controlador + nó de metadados│
 │  (CLI)     │ ◄─────────────────────────────────────── │ SQLite: dirs, files, chunks, │
 │ blocos,    │                                          │ replicas · locks/commit      │
 │ SHA-256,   │                                          │ monitor de heartbeats        │
 │ AES-GCM    │                                          │ re-replicação (prioridade)   │
 └─────┬──────┘                                          └───────▲──────────┬───────────┘
       │ 2 PUT/GET de blocos (HTTP, direto, plano de dados)       │ heartbeat │ pede cópia
       ▼                                                          │ registro  ▼
 ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌ ─ ─ ─ ┐      │
 │ nó 1  │ │ nó 2  │ │ nó 3  │ │ nó 4  │ │ nó 5  │   nó 6 (extra, entra em execução)
 │ m1/d1 │ │ m2/d1 │ │ m3/d1 │ │ m4/d1 │ │ m5/d1 │ └ ─ ─ ─ ┘
 └───────┘ └───────┘ └───────┘ └───────┘ └───────┘   cada nó: máquina simulada + disco (volume Docker)
```

- **Controlador e nó de metadados são o mesmo processo** (`controller.py`), como permitido; os papéis são separados no código
  (monitoramento/posicionamento/re-replicação × árvore de diretórios/mapa de blocos).
- **Plano de controle × plano de dados:** o controlador nunca recebe conteúdo de arquivo. O cliente pede alocação, recebe a lista de N nós
  por bloco e envia **diretamente** aos nós, em paralelo. Os nós copiam entre si quando o controlador manda (re-replicação).
- **Nó de armazenamento:** um disco (diretório `/data`, volume). Máquina e disco são atributos (`MACHINE`, `DISK`): vários discos podem
  compartilhar uma máquina.

## 2. Protocolos e formatos de mensagem

REST/JSON sobre HTTP (escolha: simples de depurar e testar; gRPC seria mais eficiente, mas não mudaria os resultados qualitativos).

| Chamada | Corpo → resposta |
|---|---|
| `POST /nodes/register` | `{id,url,machine,disk,total,used,chunks:{id:sha256}}` → `{delete:[ids obsoletos]}` |
| `POST /nodes/heartbeat` | `{id,used,total,chunks?}` (a cada 2 s; lista de blocos a cada 10 batimentos) → `{delete:[...]}`; 404 ⇒ o nó se registra de novo |
| `POST /files/allocate` | `{path,size,sha256,chunks:[{index,size,sha256}],replicas?}` → `{version,chunk_ids,targets:{idx:[{id,url}]},write_quorum,warnings}` |
| `PUT {nó}/chunks/{id}` | corpo = bytes, cabeçalho `X-Sha256` → `{ok,sha256}`; **422 se o hash não confere** |
| `POST /files/commit` | `{version,stored:{idx:[nós que confirmaram]}}` → `{path,state}`; 503 se faltou quórum |
| `GET /files/stat` | metadados: tamanho, hash, data, N, estado, blocos com localização e estado dos nós |
| `GET {nó}/chunks/{id}` | bytes do bloco |
| `POST /report-corrupt` | `{chunk_id,node_id}` (cliente na leitura ou nó no scrubbing) |
| `POST {nó}/replicate` | `{chunk_id,source_url,sha256}`: o nó puxa de outro, verifica o hash e grava |
| `/dirs`, `/files` (DELETE), `/files/move`, `/nodes/{id}/drain`, `/status`, `/metrics` | demais operações |

Logs: uma linha JSON por evento `{ts, component, event, ...file|chunk|node}` (ex.: `NODE_DEAD`, `REREPLICATION_STARTED`,
`CHUNK_STORED`, `SCRUB_CORRUPT_FOUND`, `FILE_COMMITTED`).

## 3. Algoritmos

**Posicionamento (RF3, RF7).** Candidatos = nós *vivos* (não suspeitos), não drenando e cujo uso, somado às reservas da alocação em curso e ao
bloco, fique ≤ `DISK_LIMIT` (90%). Política: **mais espaço livre primeiro** (desempate aleatório). 1ª passada escolhe **máquinas
distintas**; se faltarem máquinas, 2ª passada completa com **discos distintos** da mesma máquina e devolve aviso. Se ainda faltarem nós:
`ALLOW_UNDER_REPLICATED=true` aceita **sub-replicada** e informa o usuário (a re-replicação completa depois); `false` rejeita com 507.

**Detecção de falhas (RF5).** Heartbeat a cada 2 s. Sem batimento por **6 s ⇒ suspeito** (ainda conta como réplica viva, para evitar
churn por atraso); **12 s ⇒ morto** (réplicas deixam de contar). Transições são logadas com hora. Medido: ~10–11 s da falha à marcação de morto.

**Re-replicação (RF5).** A cada 1 s o controlador lista blocos com réplicas vivas < N, ordena por **menos réplicas vivas primeiro**
(prioridade), e dispara até `MAX_REREPL` cópias simultâneas (pool de threads). Destino: nó vivo que não tem o bloco, em máquina diferente das
réplicas vivas. Origem: réplica viva. O destino puxa o bloco da origem, **verifica o SHA-256** e só então o controlador registra a réplica.
Banda por cópia limitável (`REPLICATION_MBPS`). O tempo em que há blocos abaixo de N é registrado (janela de vulnerabilidade).

**Integridade (RF4).** (a) o nó recusa gravar bloco cujo hash não confere (422) e o cliente só conta a réplica se o hash devolvido bate;
(b) o cliente verifica cada bloco na leitura e o hash do arquivo inteiro no fim; se um bloco estiver ruim, tenta outra réplica e reporta;
(c) **scrubbing**: a cada 30 s cada nó relê seus blocos e compara com o hash gravado; corrompido ⇒ apaga e avisa o controlador, que o substitui.
Blocos de 4 MB, cada um com seu hash, além do hash do arquivo.

**Nó que volta / descoberta (RF6).** Ao (re)registrar, o nó envia `{bloco: sha256 real}`. O controlador **aproveita** os blocos que existem
nos metadados com o mesmo hash, **descarta** (manda apagar) blocos desconhecidos, obsoletos (arquivo removido/substituído) ou com hash
diferente. Réplicas em excesso (ex.: nó voltou depois da re-replicação) são aparadas, removendo do nó mais cheio.

**Drain (RF7).** `drain` marca o nó como não-vivo para fins de contagem de réplicas e de posicionamento: o laço de re-replicação copia seus
blocos para outros nós; quando nenhum bloco depende dele, pode ser retirado.

## 4. Concorrência e consistência (RF8)

- **Escrita em duas fases:** `allocate` (cria uma *versão* pendente com ids de bloco novos) → envio dos blocos → `commit`, que **troca a versão
  numa única transação SQLite** (apaga a versão antiga, insere a nova). O arquivo só fica visível no commit: **leitura nunca devolve arquivo
  parcialmente escrito**. Falha no meio da gravação: o pendente expira em 120 s e os blocos órfãos são apagados pelos nós (relatório periódico).
- **Dois escritores no mesmo caminho:** *last-writer-wins* pela ordem de commit (testado: o resultado é exatamente uma das versões).
- **Modelo:** consistência **forte** nos metadados (um controlador serializa tudo sob lock + transação). **Quórum de escrita W=2, N=3:** confirma
  ao cliente após 2 réplicas verificadas; a terceira é completada em segundo plano (se faltar, o arquivo fica *sub-replicado* e a
  re-replicação completa). Leitura: de qualquer réplica verificada por hash.
- **CAP:** em partição, o sistema escolhe **consistência** nos metadados (sem controlador não há escrita nem resolução de nomes: indisponível
  para metadados), enquanto os blocos já conhecidos continuam legíveis a quem tem a localização. É um sistema **CP** nos metadados, como HDFS/GFS.

## 5. Criptografia e hash (RF9)

- **Onde cifra:** no **cliente** (AES-256-GCM, biblioteca `cryptography`, nonce aleatório de 12 B por bloco, sem implementação própria).
  Nós e controlador nunca veem texto claro nem a chave. **Chave:** só com o cliente (`DFS_KEY` em hex ou arquivo `DFS_KEY_FILE`).
- **Hash:** dos **blocos sobre o conteúdo cifrado** (é o que o nó guarda; assim nós e scrubbing verificam sem a chave); do **arquivo sobre o texto
  claro** (verificação ponta a ponta no cliente). GCM adiciona autenticação: adulteração é detectada também na decifragem.
- Teste F08: um marcador conhecido não é encontrado em nenhum disco quando a cifra está ligada.

## 6. Persistência dos metadados (RF10)

SQLite em volume Docker (`dirs`, `files`, `chunks`, `replicas`), com WAL. O reinício do controlador recarrega tudo; o estado volátil (lista de
nós) é reconstruído porque cada nó, ao receber 404 no heartbeat, **se registra de novo** (teste T04). Escolha por simplicidade e
atomicidade transacional; limite: um único arquivo/processo.

## 7. Escala esperada e limites

Projetado/testado para: **1 controlador, 5–6 nós, centenas de arquivos, dezenas de MB**. Limites da arquitetura:
(1) **controlador único** é ponto único de falha de *disponibilidade* (não de dados: reinicia e reconstrói o estado) e gargalo de metadados:
as operações são serializadas por um lock global e a re-replicação percorre todos os blocos a cada segundo (O(blocos)); (2) SQLite não escala
a milhões de arquivos; (3) metadados em memória de nós e estados de pendência são voláteis. Para 10×–100×: metadados particionados/
replicados com Raft (como HDFS HA/Ceph MON), re-replicação orientada a eventos (fila por nó) em vez de varredura, banco de metadados
distribuído e *erasure coding* para reduzir o custo de N× de espaço (como MinIO).

## 8. Limitações conhecidas

- Controlador único (sem eleição/consenso): se cair, não há novas gravações/consultas até reiniciar (os dados não se perdem).
- Cliente carrega o arquivo inteiro na memória (blocos de 4 MB não são transmitidos em *stream*): limita o tamanho dos arquivos testados.
- A re-replicação não tem limite global de banda, só por cópia e por concorrência.
- Domínios de falha (rack/zona) não implementados (só nó e máquina).
- Bloco com **todas** as réplicas em nós mortos fica "perdido" até um deles voltar (zero perda só vale com < N falhas simultâneas).
- Mover diretórios inteiros não é suportado (só arquivos).

## 9. Divisão de tarefas

Dupla: Letícia Cavalcanti e Rodrigo Oliveira.

**Letícia Cavalcanti** (usuário Git `leticiacavalcaanti`): projeto e implementação do DFS (controlador e metadados, nós de armazenamento com
verificação de hash e scrubbing, cliente CLI com criptografia opcional, `docker-compose.yml`), documentação (README e este relatório) e
testes funcionais, de falha e de desempenho, com os dados brutos e o relatório de testes.

| Commit | Descrição |
|---|---|
| `44a4c71` | Adiciona DFS: controlador, nós de armazenamento e cliente CLI |
| `7c55007` | Documenta arquitetura, protocolos e decisões do DFS |
| `910355f` | Adiciona testes funcionais, de falha e de desempenho do DFS com dados brutos |

**Rodrigo Oliveira:** *preencher com a parte dele e os commits dele (a atividade exige commits de todos os integrantes).*
