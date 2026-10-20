"use client";
import { market } from "../lib/api";

export default function OrdersTable({ orders, token, onChanged }) {
  const cancel = async (id) => {
    try {
      await market.cancelOrder(token, id);
    } finally {
      onChanged();
    }
  };

  return (
    <table>
      <thead>
        <tr><th>#</th><th>Ativo</th><th>Lado</th><th>Preço</th><th>Executado</th><th>Status</th><th /></tr>
      </thead>
      <tbody>
        {orders.slice(0, 15).map((o) => (
          <tr key={o.id}>
            <td>{o.id}</td>
            <td>{o.symbol}</td>
            <td className={o.side === "BUY" ? "up" : "down"}>{o.side === "BUY" ? "Compra" : "Venda"}</td>
            <td>{Number(o.price).toFixed(2)}</td>
            <td>{o.filled}/{o.quantity}</td>
            <td>{o.status}</td>
            <td>
              {(o.status === "OPEN" || o.status === "PARTIAL") && (
                <button className="link" onClick={() => cancel(o.id)}>cancelar</button>
              )}
            </td>
          </tr>
        ))}
        {orders.length === 0 && <tr><td colSpan={7} className="muted">Nenhuma ordem enviada</td></tr>}
      </tbody>
    </table>
  );
}
