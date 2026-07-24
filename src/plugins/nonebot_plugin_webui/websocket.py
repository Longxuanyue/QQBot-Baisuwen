"""
WebSocket 端点 — Token 状态推送（一期）和实时事件广播（二期预留）
"""

import asyncio
import json
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from nonebot import logger

from .auth import token_store
from .config import TOKEN_TTL


class WSConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # token_watchers: {token: WebSocket}
        self._token_watchers: dict[str, WebSocket] = {}
        # broadcast_clients: set[WebSocket]
        self._broadcast_clients: set[WebSocket] = set()

    async def handle_connection(self, websocket: WebSocket):
        """处理新 WebSocket 连接"""
        await websocket.accept()

        try:
            # 等待客户端发送第一条消息（订阅类型）
            data = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            msg = json.loads(data)

            msg_type = msg.get("type", "")

            if msg_type == "watch_token":
                token = msg.get("token", "")
                await self._watch_token(websocket, token)
            elif msg_type == "subscribe":
                # 二期：广播订阅
                await self._subscribe_broadcast(websocket)
            else:
                await websocket.send_json({"type": "error", "message": f"未知消息类型: {msg_type}"})
                await websocket.close()

        except asyncio.TimeoutError:
            await websocket.close(code=1000, reason="客户端未发送订阅消息")
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WebSocket 异常: {e}")

    async def _watch_token(self, websocket: WebSocket, token: str):
        """Token 验证监听：等待用户通过 QQ 验证 token"""
        self._token_watchers[token] = websocket
        deadline = time.time() + TOKEN_TTL

        try:
            while time.time() < deadline:
                result = token_store.check(token)
                if result is not None:
                    # Token 已验证
                    from .auth import create_session
                    session = create_session(result["user_id"])
                    await websocket.send_json({
                        "type": "token_verified",
                        "session": session,
                        "user_id": result["user_id"],
                    })
                    return

                await asyncio.sleep(1)

            # 超时
            await websocket.send_json({"type": "token_expired"})

        except WebSocketDisconnect:
            pass
        finally:
            self._token_watchers.pop(token, None)

    async def _subscribe_broadcast(self, websocket: WebSocket):
        """订阅广播消息（二期）"""
        self._broadcast_clients.add(websocket)
        try:
            while True:
                # 保持连接，等待消息（心跳）
                await asyncio.sleep(30)
                try:
                    await websocket.send_json({"type": "heartbeat", "ts": time.time()})
                except Exception:
                    break
        except WebSocketDisconnect:
            pass
        finally:
            self._broadcast_clients.discard(websocket)

    async def broadcast(self, event_type: str, data: dict = None):
        """向所有广播客户端推送事件（二期）"""
        dead = set()
        payload = {"type": event_type, "data": data or {}, "ts": time.time()}
        for ws in self._broadcast_clients:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        self._broadcast_clients -= dead


ws_manager = WSConnectionManager()
