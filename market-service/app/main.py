"""market-service: API de mercado (REST) e atualizações em tempo real (WebSocket)."""
from decimal import Decimal
from typing import Literal

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import engine
from .auth import User, current_user, user_from_token
from .observability import log_event
from .realtime import ConnectionManager

app = FastAPI(title="market-service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = ConnectionManager()


class OrderRequest(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,10}$")
    side: Literal["BUY", "SELL"]
    price: Decimal = Field(gt=0, le=1_000_000, max_digits=10, decimal_places=2)
    quantity: int = Field(gt=0, le=100_000)


@app.exception_handler(engine.MarketError)
async def market_error_handler(_, err: engine.MarketError):
    return JSONResponse(status_code=err.status_code, content={"detail": str(err)})


@app.get("/health")
def health():
    return {"status": "ok", "online": len(manager.online_users())}


@app.get("/assets")
def assets(_: User = Depends(current_user)):
    return engine.list_assets()


@app.get("/book/{symbol}")
def book(symbol: str, _: User = Depends(current_user)):
    return engine.get_book(symbol.upper())


@app.get("/portfolio")
def portfolio(user: User = Depends(current_user)):
    return engine.get_portfolio(user.id, user.username)


@app.get("/online")
def online(_: User = Depends(current_user)):
    return {"users": manager.online_users()}


@app.post("/orders", status_code=201)
async def create_order(body: OrderRequest, user: User = Depends(current_user)):
    # O engine é síncrono (banco); roda em thread para não travar o event loop.
    result = await run_in_threadpool(
        engine.place_order, user.id, user.username, body.symbol, body.side, body.price, body.quantity
    )
    await _publish(result)
    return {"order": next(o for o in result["orders"] if o["id"] == result["order_id"]), "trades": result["trades"]}


@app.get("/orders")
def my_orders(user: User = Depends(current_user)):
    return engine.list_orders(user.id)


@app.get("/orders/{order_id}")
def order_status(order_id: int, user: User = Depends(current_user)):
    return engine.get_order(user.id, order_id)


@app.delete("/orders/{order_id}")
async def cancel_order(order_id: int, user: User = Depends(current_user)):
    result = await run_in_threadpool(engine.cancel_order, user.id, order_id)
    await manager.send_to_users({"type": "order_update", "order": result["order"]}, {user.id})
    await manager.broadcast({"type": "book_update", **result["book"]})
    return result["order"]


@app.get("/trades")
def my_trades(user: User = Depends(current_user)):
    return engine.list_trades(user.id)


async def _publish(result: dict):
    """Notifica os clientes afetados: livro e preço para todos, ordens para os donos."""
    book = result["book"]
    await manager.broadcast({"type": "book_update", **book})
    if result["trades"]:
        await manager.broadcast({"type": "price_update", **result["asset"]})
        for trade in result["trades"]:
            await manager.broadcast({"type": "trade", **trade})
    for order in result["orders"]:
        await manager.send_to_users({"type": "order_update", "order": order}, {order["user_id"]})
    log_event("CLIENTS_NOTIFIED", order_id=result["order_id"])


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(...)):
    try:
        user: User = user_from_token(token)
    except jwt.PyJWTError:
        await ws.close(code=4401)
        return
    await ws.accept()
    manager.add(ws, user.id, user.username)
    log_event("CLIENT_CONNECTED", user=user.username)
    await ws.send_json({"type": "snapshot", "assets": await run_in_threadpool(engine.list_assets)})
    await manager.broadcast({"type": "presence", "users": manager.online_users()})
    try:
        while True:
            await ws.receive_text()  # mantém a conexão; mensagens do cliente são ignoradas
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove(ws)
        log_event("CLIENT_DISCONNECTED", user=user.username)
        await manager.broadcast({"type": "presence", "users": manager.online_users()})
