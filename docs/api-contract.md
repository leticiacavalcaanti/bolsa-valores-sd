# Contrato da API

Autenticação: `Authorization: Bearer <access_token>` (JWT HS256, validade de 8 h).
Valores monetários são números em reais com 2 casas decimais.

## auth-service (`:8001`)

| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| POST | `/register` | `{username, password}` | 201 `{id, username}`; 409 se já existe; 403 se usar o prefixo `npc_` |
| POST | `/login` | `{username, password}` | `{access_token, token_type, user:{id, username}}`; 401 se inválido |
| GET | `/me` | — | `{id, username}` |
| POST | `/internal/npc-session` | `{username: "npc_..."}` + header `X-Internal-Key` | token de agente (uso interno) |

`username`: 3–20 caracteres (`A-Za-z0-9_`). `password`: 6–64 caracteres.

## market-service (`:8002`)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/assets` | Lista `{symbol, name, open_price, last_price, volume, change_pct}` |
| GET | `/book/{symbol}` | `{symbol, bids:[{price, quantity}], asks:[...]}` (10 melhores níveis) |
| GET | `/portfolio` | `{balance, available, equity, profit, positions:[{symbol, quantity, avg_price, last_price, market_value, profit}]}` |
| POST | `/orders` | Corpo `{symbol, side: "BUY"\|"SELL", price, quantity}` → 201 `{order, trades}`; 422 se saldo/ativos insuficientes |
| GET | `/orders` | Últimas 50 ordens do usuário |
| GET | `/orders/{id}` | Status de uma ordem própria (404 se não for sua) |
| DELETE | `/orders/{id}` | Cancela ordem própria aberta (404 se não for sua; 409 se já encerrada) |
| GET | `/trades` | Últimas 50 negociações do usuário |
| GET | `/online` | Investidores conectados |

Status de ordem: `OPEN`, `PARTIAL`, `FILLED`, `CANCELLED`.
Erros têm a forma `{"detail": "mensagem"}`.

## WebSocket

`ws://localhost:8002/ws?token=<jwt>` — token inválido fecha a conexão com código `4401`.

Mensagens do servidor (JSON, campo `type`):

| type | Destino | Conteúdo |
|---|---|---|
| `snapshot` | quem conecta | `assets` atuais |
| `presence` | todos | `users` conectados |
| `book_update` | todos | `symbol`, `bids`, `asks` |
| `price_update` | todos | `symbol`, `last_price`, `volume`, `change_pct` |
| `trade` | todos | negociação executada |
| `order_update` | dono da ordem | `order` com status e quantidade executada |

Ordens e consultas pessoais usam REST; o WebSocket é só para eventos do servidor para o cliente.
