import { brl } from "../lib/api";

export default function Portfolio({ portfolio }) {
  if (!portfolio) return <section className="card wide muted">Carregando carteira...</section>;
  const profitClass = portfolio.profit >= 0 ? "up" : "down";
  return (
    <section className="card wide">
      <div className="stats">
        <div><span className="muted">Saldo</span><strong>{brl(portfolio.balance)}</strong></div>
        <div><span className="muted">Disponível</span><strong>{brl(portfolio.available)}</strong></div>
        <div><span className="muted">Patrimônio</span><strong>{brl(portfolio.equity)}</strong></div>
        <div><span className="muted">Lucro/prejuízo</span><strong className={profitClass}>{brl(portfolio.profit)}</strong></div>
      </div>
      {portfolio.positions.length > 0 && (
        <table>
          <thead>
            <tr><th>Ativo</th><th>Qtd</th><th>Preço médio</th><th>Atual</th><th>Lucro</th></tr>
          </thead>
          <tbody>
            {portfolio.positions.map((p) => (
              <tr key={p.symbol}>
                <td>{p.symbol}</td>
                <td>{p.quantity}</td>
                <td>{brl(p.avg_price)}</td>
                <td>{brl(p.last_price)}</td>
                <td className={p.profit >= 0 ? "up" : "down"}>{brl(p.profit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
