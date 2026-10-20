"""npc-service: sobe os investidores virtuais e os mantém operando."""
import asyncio
import logging
import os

import httpx

from .agents import MarketMaker, Momentum, Noise

logging.basicConfig(level=logging.INFO, format='{"ts": "%(asctime)s", "service": "npc", "msg": "%(message)s"}')
logging.getLogger("httpx").setLevel(logging.WARNING)  # uma linha por requisição polui o log
log = logging.getLogger("npc")

AUTH_URL = os.environ.get("AUTH_URL", "http://auth-service:8000")
MARKET_URL = os.environ.get("MARKET_URL", "http://market-service:8000")
INTERNAL_KEY = os.environ["INTERNAL_KEY"]
INTERVAL = float(os.environ.get("NPC_INTERVAL", "4"))


async def wait_for_services():
    """Os serviços podem subir depois do npc-service: espera em vez de falhar."""
    async with httpx.AsyncClient(timeout=3) as client:
        for url in (f"{AUTH_URL}/health", f"{MARKET_URL}/health"):
            while True:
                try:
                    (await client.get(url)).raise_for_status()
                    break
                except httpx.HTTPError:
                    log.info("aguardando %s", url)
                    await asyncio.sleep(2)


async def main():
    await wait_for_services()
    common = dict(auth_url=AUTH_URL, market_url=MARKET_URL, internal_key=INTERNAL_KEY, interval=INTERVAL)
    agents = [
        MarketMaker("npc_maker1", spread=0.01, **common),
        MarketMaker("npc_maker2", spread=0.025, **common),
        Momentum("npc_trend", **common),
        Noise("npc_cauteloso", risk=0.005, **common),
        Noise("npc_ousado", risk=0.03, **common),
    ]
    log.info("iniciando %d agentes", len(agents))
    await asyncio.gather(*(agent.run() for agent in agents))


if __name__ == "__main__":
    asyncio.run(main())
