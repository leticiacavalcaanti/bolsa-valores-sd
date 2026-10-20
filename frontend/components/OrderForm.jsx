"use client";
import { useState } from "react";
import { market } from "../lib/api";

export default function OrderForm({ token, symbol, onPlaced }) {
  const [side, setSide] = useState("BUY");
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [message, setMessage] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setMessage(null);
    try {
      const { order, trades } = await market.placeOrder(token, {
        symbol, side, price: String(price).replace(",", "."), quantity: Number(quantity),
      });
      setMessage({ ok: true, text: `Ordem #${order.id} ${order.status} (${trades.length} negociação(ões))` });
      onPlaced();
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    }
  };

  return (
    <form onSubmit={submit} className="order-form">
      <div className="toggle">
        <button type="button" className={side === "BUY" ? "active buy" : ""} onClick={() => setSide("BUY")}>Comprar</button>
        <button type="button" className={side === "SELL" ? "active sell" : ""} onClick={() => setSide("SELL")}>Vender</button>
      </div>
      <input value={symbol} readOnly aria-label="Ativo" />
      <input placeholder="Preço limite (R$)" inputMode="decimal" value={price}
             onChange={(e) => setPrice(e.target.value)} required />
      <input placeholder="Quantidade" inputMode="numeric" value={quantity}
             onChange={(e) => setQuantity(e.target.value)} required />
      <button>Enviar ordem</button>
      {message && <p className={message.ok ? "up" : "error"}>{message.text}</p>}
    </form>
  );
}
