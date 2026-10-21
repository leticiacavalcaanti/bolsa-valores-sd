import { price, signedPct, tone } from "../lib/format";

export default function AssetTable({ assets, selected, onSelect }) {
  if (assets.length === 0) return <p className="empty">Carregando cotações...</p>;
  return (
    <ul className="assets">
      {assets.map((a) => (
        <li key={a.symbol}>
          <button type="button" className="asset" aria-pressed={a.symbol === selected} onClick={() => onSelect(a.symbol)}>
            <span className="sym">{a.symbol}</span>
            <span className="num px">{price(a.last_price)}</span>
            <span className="name" title={a.name}>{a.name}</span>
            <span className={`num chg ${tone(a.change_pct)}`}>{signedPct(a.change_pct)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
