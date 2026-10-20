export default function AssetTable({ assets, selected, onSelect }) {
  return (
    <table>
      <thead>
        <tr><th>Ativo</th><th>Preço</th><th>Var.</th><th>Volume</th></tr>
      </thead>
      <tbody>
        {assets.map((a) => (
          <tr key={a.symbol} className={a.symbol === selected ? "selected" : "clickable"} onClick={() => onSelect(a.symbol)}>
            <td title={a.name}>{a.symbol}</td>
            <td>{Number(a.last_price).toFixed(2)}</td>
            <td className={a.change_pct >= 0 ? "up" : "down"}>{Number(a.change_pct).toFixed(2)}%</td>
            <td>{a.volume}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
