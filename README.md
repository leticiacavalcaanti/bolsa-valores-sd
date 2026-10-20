# Simulador de Bolsa de Valores Multiplayer

Projeto P1 de Sistemas Distribuídos (UFS, COMP0470). Vários investidores negociam ativos virtuais
simultaneamente por um Home Broker web, com um mercado mantido por microsserviços e investidores
automatizados (NPCs).

## Como executar

Requisitos: Docker e Docker Compose.

```bash
docker compose up -d --build
```

| Componente | URL |
|---|---|
| Home Broker (Next.js) | http://localhost:3000 |
| auth-service (docs Swagger) | http://localhost:8001/docs |
| market-service (docs Swagger) | http://localhost:8002/docs |

1. Abra o Home Broker em duas abas (ou navegadores), cadastre dois usuários e negocie entre eles e com os NPCs.
2. Para parar: `docker compose down` (use `-v` para apagar também o banco).

Configuração opcional por variáveis de ambiente (ver `.env.example`): `JWT_SECRET`, `INTERNAL_KEY`.

## Testes

Com o sistema no ar: `python tests/smoke_test.py` (autenticação, validações, concorrência sobre o saldo).

## Estrutura

```
auth-service/    cadastro, login e JWT
market-service/  ativos, ordens, livro de ofertas, matching engine, carteira, WebSocket
npc-service/     investidores virtuais (market makers, momentum, ruído)
frontend/        Home Broker (Next.js)
db/init.sql      esquema do PostgreSQL e ativos iniciais
docs/            proposta, arquitetura e contrato da API
tests/           testes de fumaça e concorrência
```

## Documentação

- [Proposta do projeto](docs/proposta.md): regras do mercado, tecnologias, consistência, tolerância a falhas, agentes e cronograma
- [Arquitetura e diagramas](docs/arquitetura.md)
- [Contrato da API](docs/api-contract.md)

## Observabilidade

Cada serviço escreve logs em JSON no stdout. Para acompanhar uma ordem do início ao fim:

```bash
docker compose logs market-service | grep '"order_id": 42'
```

O fluxo registrado é `ORDER_RECEIVED → ORDER_VALIDATED → ORDER_BOOK_INSERTED → MATCH_FOUND → TRADE_EXECUTED → PORTFOLIO_UPDATED → CLIENTS_NOTIFIED`.
