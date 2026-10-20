function Side({ title, levels, className }) {
  return (
    <table>
      <thead>
        <tr><th>{title}</th><th>Qtd</th></tr>
      </thead>
      <tbody>
        {levels.map((l) => (
          <tr key={l.price}>
            <td className={className}>{Number(l.price).toFixed(2)}</td>
            <td>{l.quantity}</td>
          </tr>
        ))}
        {levels.length === 0 && <tr><td colSpan={2} className="muted">vazio</td></tr>}
      </tbody>
    </table>
  );
}

export default function OrderBook({ book }) {
  return (
    <div className="two-cols">
      <Side title="Compra" levels={book.bids} className="up" />
      <Side title="Venda" levels={book.asks} className="down" />
    </div>
  );
}
