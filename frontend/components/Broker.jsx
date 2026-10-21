"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { market } from "../lib/api";
import { useMarket } from "../lib/useMarket";
import { price, qty, signedPct, time, tone, userIdFromToken } from "../lib/format";
import AssetTable from "./AssetTable";
import Mark from "./Mark";
import OrderBook from "./OrderBook";
import OrderForm from "./OrderForm";
import OrdersTable from "./OrdersTable";
import Portfolio from "./Portfolio";

function Panel({ title, meta, className = "", children, bare = false }) {
  return (
    <section className={`panel ${className}`} aria-label={title}>
      <header className="panel-head">
        <h2>{title}</h2>
        {meta && <span className="meta">{meta}</span>}
      </header>
      {bare ? children : <div className="panel-body scroll">{children}</div>}
    </section>
  );
}

function trend(change) {
  const n = Number(change ?? 0);
  if (n > 0) return `Sobe ${signedPct(n).slice(1)} desde a abertura`;
  if (n < 0) return `Cai ${signedPct(n).slice(1)} desde a abertura`;
  return "Estável desde a abertura";
}

export default function Broker({ session, onSignOut }) {
  const { token, username } = session;
  const [symbol, setSymbol] = useState("CAJU3");
  const [portfolio, setPortfolio] = useState(null);
  const [orders, setOrders] = useState([]);
  const [trades, setTrades] = useState([]);
  const [preset, setPreset] = useState(null);
  const { connected, assets, book, online, feed, version } = useMarket(token, symbol, onSignOut);
  const myId = useMemo(() => userIdFromToken(token), [token]);
  const asset = assets.find((a) => a.symbol === symbol);

  const refreshPersonal = useCallback(async () => {
    try {
      const [p, o, t] = await Promise.all([market.portfolio(token), market.orders(token), market.trades(token)]);
      setPortfolio(p);
      setOrders(o);
      setTrades(t);
    } catch (err) {
      if (err.status === 401) onSignOut();
    }
  }, [token, onSignOut]);

  // Refaz carteira/ordens/negociações a cada mudança sinalizada pelo servidor ou reconexão.
  useEffect(() => {
    refreshPersonal();
  }, [version, refreshPersonal]);

  const openOrders = orders.filter((o) => o.status === "OPEN" || o.status === "PARTIAL").length;

  return (
    <>
      <header className="topbar">
        <div className="brand"><Mark />Home Broker</div>
        <span className={connected ? "status" : "status off"} role="status">
          <span className="dot" />{connected ? "Conectado" : "Reconectando..."}
        </span>
        <span className="muted online">{online.length} {online.length === 1 ? "investidor online" : "investidores online"}</span>
        <span className="spacer" />
        <span className="user">
          <span className="avatar" aria-hidden="true">{username.slice(0, 1)}</span>
          <span className="username">{username}</span>
        </span>
        <button className="btn" onClick={onSignOut}>Sair</button>
      </header>

      <main className="canvas">
        <div className="quote">
          <div className="quote-id">
            <h1>{symbol}<span>{asset?.name ?? ""}</span></h1>
            <p className="finding">{asset ? trend(asset.change_pct) : "Carregando cotação..."}</p>
          </div>
          <div className="quote-figures">
            <div className="quote-cell">
              <span className="label">Abertura</span>
              <span className="value num">{asset ? price(asset.open_price) : "—"}</span>
            </div>
            <div className="quote-cell">
              <span className="label">Volume</span>
              <span className="value num">{asset ? qty(asset.volume) : "—"}</span>
            </div>
            <div className="quote-cell">
              <span className="label">Variação</span>
              <span className={`value num ${asset ? tone(asset.change_pct) : ""}`}>{asset ? signedPct(asset.change_pct) : "—"}</span>
            </div>
            <div className="quote-cell">
              <span className="label">Último preço (R$)</span>
              <span className="quote-price num">{asset ? price(asset.last_price) : "—"}</span>
            </div>
          </div>
        </div>

        <div className="grid">
          <Panel title="Ativos" meta={`${assets.length} papéis`} className="span-3 row-a">
            <AssetTable assets={assets} selected={symbol} onSelect={setSymbol} />
          </Panel>

          <Panel title={`Livro de ofertas ${symbol}`} meta="10 melhores níveis" className="span-5 row-a">
            <OrderBook book={book} onPick={(p) => setPreset({ price: p })} />
          </Panel>

          <Panel title="Nova ordem" meta="Limitada" className="span-4 row-a">
            <OrderForm token={token} symbol={symbol} onPlaced={refreshPersonal} preset={preset}
                       available={portfolio?.available} />
          </Panel>

          <Panel title="Carteira" meta={portfolio ? `${portfolio.positions.length} posições` : ""} className="span-8 row-b" bare>
            <Portfolio portfolio={portfolio} />
          </Panel>

          <Panel title="Ao vivo" meta="Negócios e ordens do pregão" className="span-4 row-b">
            {feed.length === 0 ? (
              <p className="empty">Aguardando eventos...</p>
            ) : (
              <ul className="tape">
                {feed.map((item, i) => (
                  <li key={item.id} className={i === 0 ? "fresh" : undefined}>
                    <time className="num">{time(Math.floor(item.id))}</time>
                    <span className="text">{item.text}</span>
                    <span />
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Minhas ordens" meta={`${openOrders} em aberto`} className="span-8 row-c">
            <OrdersTable orders={orders} token={token} onChanged={refreshPersonal} />
          </Panel>

          <Panel title="Negociações" meta="Suas execuções" className="span-4 row-c">
            {trades.length === 0 ? (
              <p className="empty">Nenhuma negociação ainda</p>
            ) : (
              <ul className="tape">
                {trades.slice(0, 8).map((t) => {
                  const bought = t.buyer_id === myId;
                  return (
                    <li key={t.id}>
                      <time className="num">{time(t.executed_at)}</time>
                      <span className="text">
                        <span className={bought ? "up" : "down"}>{bought ? "Compra" : "Venda"}</span>{" "}
                        {t.symbol}: {qty(t.quantity)} @ {price(t.price)}
                      </span>
                      <span className="num muted">{price(Number(t.price) * Number(t.quantity))}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>
      </main>
    </>
  );
}
