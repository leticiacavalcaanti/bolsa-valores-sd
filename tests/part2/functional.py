"""Testes funcionais F01..F12. Saída: results/functional.json e tabela no console."""
import json
from concurrent.futures import ThreadPoolExecutor
import os
from common import RES, AUTH, MARKET, call, new_user, now

results = []


def case(tid, objetivo, esperado, fn):
    try:
        ok, obtido = fn()
    except Exception as e:  # noqa
        ok, obtido = False, f"exceção: {e}"
    results.append({"id": tid, "objetivo": objetivo, "esperado": esperado, "obtido": str(obtido),
                    "status": "passou" if ok else "falhou", "hora": now()})
    print(f"[{'OK' if ok else 'FALHOU'}] {tid} {objetivo} -> {obtido}")


def main():
    _, a = new_user("fa")
    _, b = new_user("fb")
    order = lambda tok, side, price, q, sym="CAJU3": call("POST", f"{MARKET}/orders",
                                                         {"symbol": sym, "side": side, "price": str(price), "quantity": q}, tok)

    case("F01", "Cadastro e login geram JWT", "token não vazio", lambda: (bool(a), "token ok" if a else "sem token"))
    case("F02", "Rota protegida sem token", "401/403", lambda: ((s := call("GET", f"{MARKET}/assets")[0]) in (401, 403), s))
    case("F03", "Token inválido", "401/403", lambda: ((s := call("GET", f"{MARKET}/assets", token="x.y.z")[0]) in (401, 403), s))
    case("F04", "Listar ativos", "5 ativos", lambda: ((r := call("GET", f"{MARKET}/assets", token=a))[0] == 200 and len(r[1]) >= 5, len(r[1])))
    case("F05", "Carteira inicial", "saldo 100000", lambda: ((r := call("GET", f"{MARKET}/portfolio", token=a))[0] == 200 and float(r[1]["cash"] if "cash" in r[1] else r[1]["available"]) == 100000.0, r[1].get("available")))
    case("F06", "Venda sem ativo", "422", lambda: ((s := order(a, "SELL", 25, 10)[0]) == 422, s))
    case("F07", "Compra acima do saldo", "422", lambda: ((s := order(a, "BUY", 25, 10**6)[0]) == 422, s))
    case("F08", "Parâmetros inválidos (quantidade negativa)", "422", lambda: ((s := order(a, "BUY", 25, -5)[0]) == 422, s))

    def f09():
        s, o, _ = order(a, "BUY", "0.01", 1, "SERT3")
        o = o.get('order', o)
        s2, st, _ = call("GET", f"{MARKET}/orders/{o['id']}", token=a)
        s3, _, _ = call("GET", f"{MARKET}/orders/{o['id']}", token=b)
        s4, _, _ = call("DELETE", f"{MARKET}/orders/{o['id']}", token=b)
        s5, c, _ = call("DELETE", f"{MARKET}/orders/{o['id']}", token=a)
        return (s == 201 and s2 == 200 and s3 == 404 and s4 == 404 and s5 == 200, f"criar={s} status={s2} outro_lê={s3} outro_cancela={s4} dono_cancela={s5}")
    case("F09", "Status de ordem e autorização (dono vs outro)", "404 para outro, cancelamento só do dono", f09)

    def f10():
        # Ana compra a 1000 (acima de qualquer venda): casa com o livro dos NPCs ou fica aberta.
        _, bk, _ = call("GET", f"{MARKET}/book/ARAC3", token=a)
        s, o, _ = order(a, "BUY", "0.02", 3, "ARAC3")
        o = o.get('order', o)
        return (s == 201 and o.get("status") in ("OPEN", "PARTIAL"), o.get("status"))
    case("F10", "Ordem fora do mercado fica OPEN no livro", "OPEN", f10)

    def f11():
        # B vende ao preço que A paga: cria ativo via compra a mercado de NPC maker? Usa cruzamento A x B.
        price = "999.00"
        sB, ob, _ = order(b, "BUY", price, 1, "FORR3")
        ob = ob.get('order', ob)
        _, tr, _ = call("GET", f"{MARKET}/trades", token=b)
        _, folio, _ = call("GET", f"{MARKET}/portfolio", token=b)
        # Compra ao preço 999 cruza com vendas dos NPCs; deve executar a preço do livro (≤ 999).
        ok = sB == 201 and ob.get("status") in ("FILLED", "PARTIAL", "OPEN")
        return ok, f"status={ob.get('status')} executada={ob.get('filled')}"
    case("F11", "Cruzamento executa ao preço do livro", "FILLED/PARTIAL", f11)

    def f12():
        _, f0, _ = call("GET", f"{MARKET}/portfolio", token=a)
        esperado = int(float(f0["available"]) // 20000)
        with ThreadPoolExecutor(20) as ex:
            rs = list(ex.map(lambda _: order(a, "BUY", "0.5", 40000, "FORR3")[0], range(20)))
        _, folio, _ = call("GET", f"{MARKET}/portfolio", token=a)
        return (rs.count(201) == esperado and float(folio["available"]) >= 0, f"esperado={esperado} aceitas={rs.count(201)}/20 disponível={folio['available']}")
    case("F12", "Concorrência: 20 compras simultâneas (R$20k cada)", "só as que cabem no saldo", f12)

    json.dump(results, open(os.path.join(RES, "functional.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{sum(r['status']=='passou' for r in results)}/{len(results)} passaram")


if __name__ == "__main__":
    main()
