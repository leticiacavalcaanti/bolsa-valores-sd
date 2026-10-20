# Arquitetura

## Componentes

```mermaid
flowchart LR
    subgraph Clientes
        HB[Home Broker<br/>Next.js]
    end
    subgraph Serviços
        AUTH[auth-service<br/>FastAPI]
        MKT[market-service<br/>FastAPI<br/>matching engine]
        NPC[npc-service<br/>agentes]
    end
    DB[(PostgreSQL<br/>schemas auth e market)]

    HB -- "REST: login/cadastro" --> AUTH
    HB -- "REST: ordens e consultas" --> MKT
    MKT -. "WebSocket: eventos" .-> HB
    NPC -- "sessão interna (chave)" --> AUTH
    NPC -- "REST: mesma API dos jogadores" --> MKT
    AUTH --> DB
    MKT --> DB
    MKT -. "valida JWT (segredo compartilhado)" .- AUTH
```

## Fluxo de uma ordem

```mermaid
sequenceDiagram
    participant J as Jogador (Home Broker)
    participant M as market-service
    participant D as PostgreSQL
    participant O as Demais clientes

    J->>M: POST /orders (JWT)
    M->>M: ORDER_RECEIVED, valida token e parâmetros
    M->>M: adquire lock do engine
    M->>D: BEGIN, trava conta, valida saldo/ativos
    M->>D: insere ordem (ORDER_BOOK_INSERTED)
    M->>D: busca ordens compatíveis (MATCH_FOUND)
    M->>D: atualiza saldos, carteiras, ordens, trades (TRADE_EXECUTED)
    M->>D: COMMIT (PORTFOLIO_UPDATED)
    M-->>J: 201 {order, trades}
    M-->>O: WebSocket: book_update, price_update, trade (CLIENTS_NOTIFIED)
    M-->>J: WebSocket: order_update (dono das ordens afetadas)
```

## Decisões

| Tema | Decisão | Justificativa |
|---|---|---|
| Estilo | Microsserviços leves por responsabilidade | Auth isolado, mercado como único dono do estado, NPCs podem cair sem afetar o mercado |
| Protocolos | REST para comandos, WebSocket para eventos | Comandos precisam de resposta e status HTTP; eventos precisam de push em tempo real |
| Consistência do mercado | Forte: lock global no engine e uma transação por ordem | Ordem total das ordens (prioridade temporal) e atomicidade de saldo, carteira e negociação |
| Consistência da interface | Eventual | O cliente recebe eventos por WebSocket e ressincroniza por REST após reconectar |
| Persistência | PostgreSQL (ACID) | Transações garantem que ordem + negociações + saldos sejam gravados juntos ou nenhum |
| Segurança | JWT, bcrypt, validação com Pydantic, dono verificado em cada ordem | Ordens de outro usuário aparecem como inexistentes |
| Agentes | Clientes comuns da API, com prefixo `npc_` reservado | O mercado não confia no cliente: o prefixo só é obtido por chave interna |

## Limitações conhecidas e evolução

- O lock global limita o throughput a um escritor. Evolução: particionar por ativo (um engine por símbolo) com saldo reservado antes do casamento.
- O market-service tem uma única instância; a falha dele é detectada e recuperada pelo `restart` do Docker e pela reconexão dos clientes, sem perda de dados confirmados.
- O banco é único (schemas separados). Evolução: um banco por serviço e/ou réplica de leitura.
