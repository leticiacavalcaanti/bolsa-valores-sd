"""Teste de fumaça: cadastro, login, ordens, casamento e concorrência.

Uso (com `docker compose up` rodando):  python tests/smoke_test.py
Usa apenas a biblioteca padrão.
"""
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

AUTH = "http://localhost:8001"
MARKET = "http://localhost:8002"


def call(method, url, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def new_user(prefix):
    name = f"{prefix}{int(time.time() * 1000) % 100000000}"[:20]
    call("POST", f"{AUTH}/register", {"username": name, "password": "senha123"})
    _, resp = call("POST", f"{AUTH}/login", {"username": name, "password": "senha123"})
    return name, resp["access_token"]


def check(label, condition):
    print(f"[{'OK' if condition else 'FALHOU'}] {label}")
    if not condition:
        raise SystemExit(1)


def main():
    _, tok_a = new_user("ana")
    _, tok_b = new_user("bia")

    status, _ = call("GET", f"{MARKET}/assets")
    check("sem token é rejeitado", status in (401, 403))

    status, assets = call("GET", f"{MARKET}/assets", token=tok_a)
    check("lista de ativos", status == 200 and len(assets) >= 5)

    # Venda sem ter o ativo deve ser rejeitada.
    status, _ = call("POST", f"{MARKET}/orders", {"symbol": "CAJU3", "side": "SELL", "price": "25", "quantity": 10}, tok_a)
    check("venda sem ativo é rejeitada", status == 422)

    # Compra acima do saldo deve ser rejeitada.
    status, _ = call("POST", f"{MARKET}/orders", {"symbol": "CAJU3", "side": "BUY", "price": "25", "quantity": 100000}, tok_a)
    check("compra sem saldo é rejeitada", status == 422)

    # Ana compra; Bia não tem ativos, então só entra no livro como compradora também.
    status, resp = call("POST", f"{MARKET}/orders", {"symbol": "SERT3", "side": "BUY", "price": "18.50", "quantity": 100}, tok_a)
    check("ordem de compra aceita e aberta", status == 201 and resp["order"]["status"] == "OPEN")

    # Concorrência: 20 compras simultâneas de R$ 10.000 com saldo de R$ 100.000 -> no máximo 10 aceitas
    # (a de 100 x 18,50 já reservou R$ 1.850).
    def buy(_):
        return call("POST", f"{MARKET}/orders", {"symbol": "ARAC3", "side": "BUY", "price": "10", "quantity": 1000}, tok_b)[0]

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(buy, range(20)))
    check("concorrência: saldo nunca é usado além do disponível", results.count(201) == 10)

    _, folio = call("GET", f"{MARKET}/portfolio", token=tok_b)
    check("saldo disponível não fica negativo", folio["available"] >= 0)

    print("Todos os testes passaram.")


if __name__ == "__main__":
    main()
