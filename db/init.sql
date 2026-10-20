-- Um schema por serviço: auth e market não compartilham tabelas
-- (comunicam-se apenas via JWT), o que facilita separar bancos depois.

CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS market;

CREATE TABLE IF NOT EXISTS auth.users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(20) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market.assets (
    symbol      VARCHAR(10) PRIMARY KEY,
    name        TEXT NOT NULL,
    open_price  NUMERIC(14,2) NOT NULL,
    last_price  NUMERIC(14,2) NOT NULL,
    volume      BIGINT NOT NULL DEFAULT 0
);

-- Conta criada sob demanda no primeiro acesso do usuário ao mercado.
CREATE TABLE IF NOT EXISTS market.accounts (
    user_id  INTEGER PRIMARY KEY,
    username VARCHAR(20) NOT NULL,
    balance  NUMERIC(14,2) NOT NULL CHECK (balance >= 0)
);

CREATE TABLE IF NOT EXISTS market.positions (
    user_id   INTEGER NOT NULL REFERENCES market.accounts(user_id),
    symbol    VARCHAR(10) NOT NULL REFERENCES market.assets(symbol),
    quantity  INTEGER NOT NULL CHECK (quantity >= 0),
    avg_price NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

CREATE TABLE IF NOT EXISTS market.orders (
    id         BIGSERIAL PRIMARY KEY,   -- ordem de chegada = prioridade temporal
    user_id    INTEGER NOT NULL REFERENCES market.accounts(user_id),
    username   VARCHAR(20) NOT NULL,
    symbol     VARCHAR(10) NOT NULL REFERENCES market.assets(symbol),
    side       VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    price      NUMERIC(14,2) NOT NULL CHECK (price > 0),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    filled     INTEGER NOT NULL DEFAULT 0,
    status     VARCHAR(10) NOT NULL DEFAULT 'OPEN'
               CHECK (status IN ('OPEN', 'PARTIAL', 'FILLED', 'CANCELLED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_orders_book ON market.orders (symbol, side, status, price, id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON market.orders (user_id, id DESC);

CREATE TABLE IF NOT EXISTS market.trades (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(10) NOT NULL REFERENCES market.assets(symbol),
    buyer_id    INTEGER NOT NULL,
    seller_id   INTEGER NOT NULL,
    buy_order   BIGINT NOT NULL,
    sell_order  BIGINT NOT NULL,
    price       NUMERIC(14,2) NOT NULL,
    quantity    INTEGER NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO market.assets (symbol, name, open_price, last_price) VALUES
    ('CAJU3', 'Cajueiro Alimentos',      25.00, 25.00),
    ('ARAC3', 'Aracaju Energia',         40.00, 40.00),
    ('SERT3', 'Sertão Tech',             18.50, 18.50),
    ('MANG3', 'Mangue Biotecnologia',    32.00, 32.00),
    ('FORR3', 'Forró Entretenimento',    12.00, 12.00)
ON CONFLICT (symbol) DO NOTHING;
