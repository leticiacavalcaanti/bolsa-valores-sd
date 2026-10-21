"use client";
import { market } from "../lib/api";
import { price, qty } from "../lib/format";

const STATUS = {
  OPEN: ["Aberta", "open"],
  PARTIAL: ["Parcial", "partial"],
  FILLED: ["Executada", "filled"],
  CANCELLED: ["Cancelada", "cancelled"],
};

export default function OrdersTable({ orders, token, onChanged }) {
  const cancel = async (id) => {
    try {
      await market.cancelOrder(token, id);
    } finally {
      onChanged();
    }
  };

  if (orders.length === 0) return <p className="empty">Nenhuma ordem enviada. Use o painel Nova ordem para começar.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="num">#</th><th>Ativo</th><th>Lado</th><th className="num">Preço</th>
            <th className="num">Executado</th><th>Status</th><th aria-label="Ações" />
          </tr>
        </thead>
        <tbody>
          {orders.slice(0, 15).map((o) => {
            const [label, cls] = STATUS[o.status] ?? [o.status, "open"];
            return (
              <tr key={o.id}>
                <td className="num muted">{o.id}</td>
                <td><span className="sym">{o.symbol}</span></td>
                <td className={o.side === "BUY" ? "up" : "down"}>{o.side === "BUY" ? "Compra" : "Venda"}</td>
                <td className="num">{price(o.price)}</td>
                <td className="num">{qty(o.filled)}<span className="muted"> / {qty(o.quantity)}</span></td>
                <td><span className={`pill ${cls}`}>{label}</span></td>
                <td className="num">
                  {(o.status === "OPEN" || o.status === "PARTIAL") && (
                    <button className="text-action" onClick={() => cancel(o.id)}>Cancelar</button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
