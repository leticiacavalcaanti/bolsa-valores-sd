import { price, qty } from "../lib/format";

function Side({ side, levels, max, onPick }) {
  const isBid = side === "bid";
  return (
    <div className={side}>
      <div className="book-head">
        {isBid ? <><span>Qtd</span><span>Compra</span></> : <><span>Venda</span><span>Qtd</span></>}
      </div>
      {levels.map((l) => {
        const width = `${Math.max((Number(l.quantity) / max) * 100, 2)}%`;
        return (
          <button type="button" key={l.price} className="level" onClick={() => onPick(l.price)}
                  title={`Usar ${price(l.price)} como preço limite`}>
            <span className="bar" style={{ width }} />
            {isBid ? (
              <><span className="num qty">{qty(l.quantity)}</span><span className="num price">{price(l.price)}</span></>
            ) : (
              <><span className="num price">{price(l.price)}</span><span className="num qty">{qty(l.quantity)}</span></>
            )}
          </button>
        );
      })}
      {levels.length === 0 && (
        <p className="book-empty">{isBid ? "Sem ofertas de compra" : "Sem ofertas de venda"}</p>
      )}
    </div>
  );
}

export default function OrderBook({ book, onPick }) {
  const all = [...book.bids, ...book.asks].map((l) => Number(l.quantity));
  const max = Math.max(1, ...all);
  const bestBid = book.bids[0]?.price;
  const bestAsk = book.asks[0]?.price;
  const spread = bestBid != null && bestAsk != null ? Number(bestAsk) - Number(bestBid) : null;

  return (
    <>
      <div className="spread">
        <span>Melhor compra <strong className="num">{bestBid != null ? price(bestBid) : "—"}</strong></span>
        <span>Spread <strong className="num">{spread != null ? price(spread) : "—"}</strong></span>
        <span>Melhor venda <strong className="num">{bestAsk != null ? price(bestAsk) : "—"}</strong></span>
      </div>
      <div className="book">
        <Side side="bid" levels={book.bids} max={max} onPick={onPick} />
        <Side side="ask" levels={book.asks} max={max} onPick={onPick} />
      </div>
      <p className="book-foot">Clique num nível para usar o preço na ordem.</p>
    </>
  );
}
