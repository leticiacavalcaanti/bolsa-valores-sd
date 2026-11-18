"""npc-service: sobe os investidores virtuais e os mantém operando."""
import asyncio
import logging
import os

import httpx

from .agents import MarketMaker, MeanReversion, Momentum, Noise, Panic

logging.basicConfig(level=logging.INFO, format='{"ts": "%(asctime)s", "service": "npc", "msg": "%(message)s"}')
logging.getLogger("httpx").setLevel(logging.WARNING)  # uma linha por requisição polui o log
log = logging.getLogger("npc")

AUTH_URL = os.environ.get("AUTH_URL", "http://auth-service:8000")
MARKET_URL = os.environ.get("MARKET_URL", "http://market-service:8000")
INTERNAL_KEY = os.environ["INTERNAL_KEY"]
INTERVAL = float(os.environ.get("NPC_INTERVAL", "4"))
SCALE = max(1, int(os.environ.get("NPC_SCALE", "1")))  # cópias de cada perfil


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
    # (nome base, classe, parâmetros). Com NPC_SCALE > 1 cada perfil é replicado: npc_trend, npc_trend_2, ...
    roster = [
        ("npc_maker1", MarketMaker, dict(spread=0.01)),
        ("npc_maker2", MarketMaker, dict(spread=0.025)),
        ("npc_trend", Momentum, {}),
        ("npc_valor", MeanReversion, {}),
        ("npc_panico", Panic, {}),
        ("npc_cauteloso", Noise, dict(risk=0.005)),
        ("npc_ousado", Noise, dict(risk=0.03)),
    ]
    agents = [
        cls(name if copy == 1 else f"{name}_{copy}", **params, **common)
        for copy in range(1, SCALE + 1)
        for name, cls, params in roster
    ]
    log.info("iniciando %d agentes (%d perfis x %d)", len(agents), len(roster), SCALE)
    await asyncio.gather(*(agent.run() for agent in agents))


if __name__ == "__main__":
    asyncio.run(main())
