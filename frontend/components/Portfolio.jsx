import { brl } from "../lib/api";
import { qty, tone } from "../lib/format";

const signedBrl = (value) => `${Number(value) > 0 ? "+" : ""}${brl(value)}`;

function Kpis({ portfolio }) {
  const cells = [
    { label: "Patrimônio", value: portfolio && brl(portfolio.equity), lead: true },
    { label: "Saldo", value: portfolio && brl(portfolio.balance) },
    { label: "Disponível", value: portfolio && brl(portfolio.available) },
    { label: "Lucro/prejuízo", value: portfolio && signedBrl(portfolio.profit), tone: portfolio && tone(portfolio.profit) },
  ];
  return (
    <div className="kpis">
      {cells.map((c) => (
        <div key={c.label} className={c.lead ? "kpi lead" : "kpi"}>
          <span className="label">{c.label}</span>
          {c.value ? <span className={`value ${c.tone ?? ""}`}>{c.value}</span>
                   : <span className="value bar-skel" aria-label="Carregando" />}
        </div>
      ))}
    </div>
  );
}

export default function Portfolio({ portfolio }) {
  return (
    <>
      <Kpis portfolio={portfolio} />
      <div className="panel-body scroll positions">
        {portfolio && portfolio.positions.length === 0 && (
          <p className="empty">Nenhuma posição em carteira. Compre um papel para montá-la.</p>
        )}
        {portfolio && portfolio.positions.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ativo</th><th className="num">Qtd</th><th className="num">Preço médio</th>
                  <th className="num">Atual</th><th className="num">Lucro</th>
                </tr>
              </thead>
              <tbody>
                {portfolio.positions.map((p) => (
                  <tr key={p.symbol}>
                    <td><span className="sym">{p.symbol}</span></td>
                    <td className="num">{qty(p.quantity)}</td>
                    <td className="num">{brl(p.avg_price)}</td>
                    <td className="num">{brl(p.last_price)}</td>
                    <td className={`num ${tone(p.profit)}`}>{signedBrl(p.profit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
