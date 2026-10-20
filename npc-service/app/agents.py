"""Investidores virtuais baseados em regras.

Todos usam a mesma API pública dos jogadores (REST + JWT): o mercado não distingue
agente de humano, o que também exercita a autenticação e as validações.

Perfis:
- MarketMaker: cota compra e venda em torno do último preço (dá liquidez ao livro).
- Momentum:    segue a tendência; compra quando o preço sobe e vende quando cai.
- Noise:       ordens aleatórias perto do preço; a agressividade define a distância.
"""
import asyncio
import logging
import random

import httpx

log = logging.getLogger("npc")


def _price(value: float) -> str:
    return f"{max(value, 0.01):.2f}"


class Agent:
    """Base: mantém sessão (re-login automático) e expõe chamadas ao mercado."""

    def __init__(self, name: str, auth_url: str, market_url: str, internal_key: str, interval: float):
        self.name = name
        self.auth_url = auth_url
        self.market_url = market_url
        self.internal_key = internal_key
        self.interval = interval
        self.token = None
        self.client = httpx.AsyncClient(timeout=5)

    async def _login(self):
        resp = await self.client.post(
            f"{self.auth_url}/internal/npc-session",
            json={"username": self.name},
            headers={"X-Internal-Key": self.internal_key},
        )
        resp.raise_for_status()
        self.token = resp.json()["access_token"]

    async def _request(self, method: str, path: str, **kwargs):
        if not self.token:
            await self._login()
        headers = {"Authorization": f"Bearer {self.token}"}
        resp = await self.client.request(method, f"{self.market_url}{path}", headers=headers, **kwargs)
        if resp.status_code == 401:  # token expirou: renova e repete uma vez
            await self._login()
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = await self.client.request(method, f"{self.market_url}{path}", headers=headers, **kwargs)
        return resp

    async def assets(self) -> list[dict]:
        resp = await self._request("GET", "/assets")
        resp.raise_for_status()
        return resp.json()

    async def order(self, symbol: str, side: str, price: float, quantity: int):
        resp = await self._request(
            "POST", "/orders",
            json={"symbol": symbol, "side": side, "price": _price(price), "quantity": quantity},
        )
        # 422 = regra de negócio (sem saldo/ativos); esperado para agentes, não é falha.
        if resp.status_code not in (201, 422):
            resp.raise_for_status()

    async def cancel_open_orders(self):
        resp = await self._request("GET", "/orders")
        resp.raise_for_status()
        for order in resp.json():
            if order["status"] in ("OPEN", "PARTIAL"):
                await self._request("DELETE", f"/orders/{order['id']}")

    async def step(self):
        raise NotImplementedError

    async def run(self):
        """Laço resiliente: se o mercado cair, tenta de novo no próximo ciclo."""
        while True:
            try:
                await self.step()
            except (httpx.HTTPError, KeyError) as err:
                log.warning("%s: falha no ciclo (%s); nova tentativa em %.0fs", self.name, err, self.interval)
                self.token = None
            await asyncio.sleep(self.interval * random.uniform(0.7, 1.3))


class MarketMaker(Agent):
    def __init__(self, *args, spread: float = 0.01, **kwargs):
        super().__init__(*args, **kwargs)
        self.spread = spread

    async def step(self):
        await self.cancel_open_orders()  # recota sem deixar ofertas velhas no livro
        for asset in await self.assets():
            last = asset["last_price"]
            qty = random.randint(20, 60)
            await self.order(asset["symbol"], "BUY", last * (1 - self.spread), qty)
            await self.order(asset["symbol"], "SELL", last * (1 + self.spread), qty)


class Momentum(Agent):
    """Compara o preço atual com o do ciclo anterior; reage se a variação passar do limiar."""

    def __init__(self, *args, threshold: float = 0.004, **kwargs):
        super().__init__(*args, **kwargs)
        self.threshold = threshold
        self.previous: dict[str, float] = {}

    async def step(self):
        for asset in await self.assets():
            symbol, last = asset["symbol"], asset["last_price"]
            before = self.previous.get(symbol, last)
            self.previous[symbol] = last
            change = (last - before) / before
            qty = random.randint(5, 25)
            if change > self.threshold:
                await self.order(symbol, "BUY", last * 1.01, qty)    # cruza o spread: executa já
            elif change < -self.threshold:
                await self.order(symbol, "SELL", last * 0.99, qty)


class Noise(Agent):
    """risk: 0.5% (conservador) a 3% (agressivo) de distância do último preço."""

    def __init__(self, *args, risk: float = 0.01, **kwargs):
        super().__init__(*args, **kwargs)
        self.risk = risk

    async def step(self):
        assets = await self.assets()
        asset = random.choice(assets)
        side = random.choice(["BUY", "SELL"])
        offset = random.uniform(-self.risk, self.risk)
        await self.order(asset["symbol"], side, asset["last_price"] * (1 + offset), random.randint(1, 15))
