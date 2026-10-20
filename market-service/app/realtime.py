"""Gerenciador de conexões WebSocket: broadcast para todos e envio por usuário."""
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: dict[WebSocket, tuple[int, str]] = {}

    def add(self, ws: WebSocket, user_id: int, username: str):
        self._connections[ws] = (user_id, username)

    def remove(self, ws: WebSocket):
        self._connections.pop(ws, None)

    def online_users(self) -> list[str]:
        return sorted({name for _, name in self._connections.values()})

    async def broadcast(self, message: dict):
        await self._send_where(message, lambda user_id: True)

    async def send_to_users(self, message: dict, user_ids: set[int]):
        await self._send_where(message, lambda user_id: user_id in user_ids)

    async def _send_where(self, message: dict, accept):
        for ws, (user_id, _) in list(self._connections.items()):
            if not accept(user_id):
                continue
            try:
                await ws.send_json(message)
            except Exception:
                # Cliente caiu sem fechar: remove para detectar a desconexão.
                self.remove(ws)
