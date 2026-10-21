"use client";
import { useEffect, useState } from "react";
import { market, brl } from "../lib/api";

export default function OrderForm({ token, symbol, onPlaced, preset, available }) {
  const [side, setSide] = useState("BUY");
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (preset) setPrice(Number(preset.price).toFixed(2).replace(".", ","));
  }, [preset]);

  const submit = async (event) => {
    event.preventDefault();
    setMessage(null);
    setBusy(true);
    try {
      const { order, trades } = await market.placeOrder(token, {
        symbol, side, price: String(price).replace(",", "."), quantity: Number(quantity),
      });
      setMessage({ ok: true, text: `Ordem #${order.id} ${order.status} (${trades.length} negociação(ões))` });
      onPlaced();
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const total = Number(String(price).replace(",", ".")) * Number(quantity);
  const buying = side === "BUY";

  return (
    <form onSubmit={submit} className="order-form">
      <div className="tabs" role="tablist" aria-label="Lado da ordem">
        <button type="button" role="tab" className="tab buy" aria-selected={buying} onClick={() => setSide("BUY")}>Comprar</button>
        <button type="button" role="tab" className="tab sell" aria-selected={!buying} onClick={() => setSide("SELL")}>Vender</button>
      </div>
      <div className="field">
        <label htmlFor="order-symbol">Ativo</label>
        <input id="order-symbol" className="input" value={symbol} readOnly aria-label="Ativo" />
      </div>
      <div className="pair">
        <div className="field">
          <label htmlFor="order-price">Preço limite (R$)</label>
          <input id="order-price" className="input input-num" placeholder="0,00" inputMode="decimal" value={price}
                 onChange={(e) => setPrice(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="order-qty">Quantidade</label>
          <input id="order-qty" className="input input-num" placeholder="0" inputMode="numeric" value={quantity}
                 onChange={(e) => setQuantity(e.target.value)} required />
        </div>
      </div>
      <div className="summary">
        <div><span>Total estimado</span><span className="num">{Number.isFinite(total) && total > 0 ? brl(total) : "—"}</span></div>
        <div><span>Disponível para compra</span><span className="num">{available != null ? brl(available) : "—"}</span></div>
      </div>
      <button className="btn btn-primary" disabled={busy}>
        {buying ? `Comprar ${symbol}` : `Vender ${symbol}`}
      </button>
      {message && <p className={`notice ${message.ok ? "ok" : "error"}`} role="status">{message.text}</p>}
    </form>
  );
}
