from typing import List
from fastapi import WebSocket
import asyncio
import logging

logger = logging.getLogger("websocket_manager")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, data: dict):
        async with self.lock:
            disconnected_sockets = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(data)
                except Exception as e:
                    logger.error(f"Error broadcasting to socket: {e}")
                    disconnected_sockets.append(connection)
            
            for conn in disconnected_sockets:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)

manager = ConnectionManager()
