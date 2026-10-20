"use client";
import { useCallback, useEffect, useState } from "react";
import { market } from "../lib/api";
import { useMarket } from "../lib/useMarket";
import AssetTable from "./AssetTable";
import OrderBook from "./OrderBook";
import OrderForm from "./OrderForm";
import OrdersTable from "./OrdersTable";
import Portfolio from "./Portfolio";

export default function Broker({ session, onSignOut }) {
  const { token, username } = session;
  const [symbol, setSymbol] = useState("CAJU3");
  const [portfolio, setPortfolio] = useState(null);
  const [orders, setOrders] = useState([]);
  const [trades, setTrades] = useState([]);
  const { connected, assets, book, online, feed, version } = useMarket(token, symbol, onSignOut);

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

  return (
    <div className="layout">
      <header>
        <strong>Home Broker</strong>
        <span className={connected ? "pill ok" : "pill bad"}>{connected ? "conectado" : "reconectando..."}</span>
        <span className="muted">{online.length} online</span>
        <span className="spacer" />
        <span>{username}</span>
        <button className="link" onClick={onSignOut}>Sair</button>
      </header>

      <Portfolio portfolio={portfolio} />

      <section className="card">
        <h2>Ativos</h2>
        <AssetTable assets={assets} selected={symbol} onSelect={setSymbol} />
      </section>

      <section className="card">
        <h2>Livro de ofertas — {symbol}</h2>
        <OrderBook book={book} />
      </section>

      <section className="card">
        <h2>Nova ordem</h2>
        <OrderForm token={token} symbol={symbol} onPlaced={refreshPersonal} />
      </section>

      <section className="card wide">
        <h2>Minhas ordens</h2>
        <OrdersTable orders={orders} token={token} onChanged={refreshPersonal} />
      </section>

      <section className="card">
        <h2>Negociações</h2>
        <ul className="feed">
          {trades.slice(0, 8).map((t) => (
            <li key={t.id}>{t.symbol}: {t.quantity} @ {Number(t.price).toFixed(2)}</li>
          ))}
          {trades.length === 0 && <li className="muted">Nenhuma negociação ainda</li>}
        </ul>
      </section>

      <section className="card">
        <h2>Ao vivo</h2>
        <ul className="feed">
          {feed.map((item) => <li key={item.id}>{item.text}</li>)}
          {feed.length === 0 && <li className="muted">Aguardando eventos...</li>}
        </ul>
      </section>
    </div>
  );
}
