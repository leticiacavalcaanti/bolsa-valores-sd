# Proposta do Projeto

## 1. Mercado

Bolsa virtual de empresas fictícias com temática sergipana. Cada jogador começa com **R$ 100.000** e negocia por um Home Broker web.

| Ativo | Empresa | Preço inicial |
|---|---|---|
| CAJU3 | Cajueiro Alimentos | R$ 25,00 |
| ARAC3 | Aracaju Energia | R$ 40,00 |
| SERT3 | Sertão Tech | R$ 18,50 |
| MANG3 | Mangue Biotecnologia | R$ 32,00 |
| FORR3 | Forró Entretenimento | R$ 12,00 |

### Regras de negociação

- Apenas **ordens limitadas** (preço máximo de compra ou mínimo de venda) em quantidades inteiras.
- **Prioridade de preço e depois temporal**: compras de maior preço e vendas de menor preço primeiro; em empate, a ordem mais antiga (menor id, atribuído dentro do lock do engine).
- A negociação ocorre ao **preço da ordem que já estava no livro**; o preço do ativo passa a ser o da última negociação.
- **Execução parcial**: a ordem permanece no livro com o restante até ser preenchida ou cancelada.
- **Reserva**: o valor de ordens de compra abertas e a quantidade de ordens de venda abertas ficam indisponíveis para novas ordens, impedindo uso duplo de saldo ou ativos.
- Um investidor não negocia com as próprias ordens.
- Só o dono cancela uma ordem.

### Investidores

- **Jogadores**: usuários cadastrados no Home Broker.
- **Agentes (NPCs)**: investidores virtuais que mantêm o mercado ativo (seção 6).

## 2. Arquitetura

Microsserviços em contêineres (Docker Compose): `auth-service`, `market-service`, `npc-service`, `frontend` e PostgreSQL. Diagramas de componentes e de sequência em [arquitetura.md](arquitetura.md).

## 3. Tecnologias e protocolos

| Camada | Escolha | Motivo |
|---|---|---|
| Backend | Python + FastAPI | Validação declarativa (Pydantic), WebSocket nativo, rápido de desenvolver |
| Frontend | Next.js (React) | Home Broker reativo, atualização por eventos |
| Banco | PostgreSQL | Transações ACID e `SELECT ... FOR UPDATE` para consistência de saldo e carteira |
| Comandos | HTTP/REST | Resposta imediata com status e erros de validação |
| Tempo real | WebSocket | Push de livro, preço, negociações e status de ordens |
| Execução | Docker Compose | Reprodutível; `restart: unless-stopped` para recuperação |

## 4. Consistência

- **Mercado (forte)**: um lock no engine serializa as ordens e cada ordem é processada em **uma única transação** (ordem, negociações, saldos, carteiras, livro e preço). Se algo falha, nada é gravado, garantindo atomicidade. O saldo é travado (`FOR UPDATE`) durante a validação e as reservas evitam duas ordens concorrentes usarem o mesmo saldo (verificado em teste com 20 requisições simultâneas).
- **Interface (eventual)**: os clientes recebem os eventos por WebSocket; após uma queda, refazem as consultas por REST e convergem para o estado do servidor.
- **Trade-off**: o lock global limita o paralelismo, mas elimina condições de corrida e deadlocks entre ativos. A evolução é o particionamento por ativo.

## 5. Tolerância a falhas

| Falha | Detecção | Reação | Estado preservado |
|---|---|---|---|
| Cliente desconecta | Fechamento ou erro de envio no WebSocket | Remove da lista de online e avisa os demais | Ordens abertas continuam no livro |
| Cliente reconecta | Novo WebSocket com o mesmo JWT | Backoff exponencial (1 s a 10 s), ressincroniza carteira, ordens e livro | Saldo, carteira e ordens (no banco) |
| Queda do market-service | Falha de conexão do cliente e dos NPCs | `restart` do Docker; clientes e NPCs tentam de novo | Tudo o que foi confirmado (commit) |
| Queda do auth-service | Login falha | Sessões já abertas seguem válidas (JWT é verificado localmente) | Sessões ativas |
| Queda no meio de uma ordem | Transação sem commit | Rollback automático do PostgreSQL | Nenhuma ordem parcial |
| Queda do npc-service | — | Mercado segue com os jogadores; NPCs retomam ao reiniciar | Carteiras dos NPCs |

Falha controlada para a demonstração: `docker compose stop market-service`, observar o indicador "reconectando..." no Home Broker, depois `docker compose start market-service` e verificar que saldo e ordens estão intactos.

## 6. Agentes (NPCs)

Algoritmos baseados em regras, que usam a mesma API pública dos jogadores:

- **MarketMaker** (`npc_maker1`, `npc_maker2`): recota compra e venda em torno do último preço, com spreads de 1 % e 2,5 %, dando liquidez.
- **Momentum** (`npc_trend`): compra quando o preço sobe mais que 0,4 % entre ciclos e vende quando cai, seguindo a tendência.
- **Noise** (`npc_cauteloso`, `npc_ousado`): ordens aleatórias perto do preço; o perfil de risco define a distância (0,5 % e 3 %).

Os NPCs começam com R$ 500.000 e 1.000 unidades de cada ativo, para haver oferta de venda desde o início.

## 7. Cronograma

| Período | Entrega |
|---|---|
| 18/10 | Repositório, banco, auth, market-service com ordens e WebSocket, NPCs |
| 19/10 | Home Broker (login, ativos, livro, ordens, carteira) |
| 20/10 | Documentação, diagramas e ensaio da demonstração |
| 21/10 | **Apresentação e entrega parcial** |
| 22–31/10 | Eventos econômicos, testes automatizados de concorrência |
| 01–15/11 | Testes de carga (5, 20, 50 e 100 usuários) e métricas |
| 16–25/11 | Observabilidade (métricas, painel), falhas controladas, segurança |
| 26–29/11 | Relatório de testes e ensaio |
| 30/11 | **Apresentação e entrega final** |

## 8. Próximos passos (Parte 2)

Eventos econômicos propagados aos agentes, métricas (Prometheus/Grafana), testes de carga, particionamento do engine por ativo, fila de eventos entre serviços e demonstração de falha com réplicas.
