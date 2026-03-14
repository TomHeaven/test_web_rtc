# signaling_server.py (最终版本 - 单一端口)
import asyncio
import json
import websockets
from typing import Set
import logging
from urllib.parse import parse_qs, urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SignalingServer:
    """
    WebRTC信令服务器 - 使用不同路径区分客户端类型
    """
    
    def __init__(self):
        self.broadcasters: Set = set()  # 视频发送端
        self.viewers: Set = set()       # 视频接收端
        
    async def register_broadcaster(self, websocket):
        """注册发送端"""
        self.broadcasters.add(websocket)
        logger.info(f"发送端已连接，当前数量: {len(self.broadcasters)}")
    
    async def register_viewer(self, websocket):
        self.viewers.add(websocket)
        logger.info(f"接收端已连接，当前数量: {len(self.viewers)}")

        if self.broadcasters:
            message = json.dumps({'type': 'new_viewer', 'message': '有新的观看者连接'})
            logger.info(f"向 {len(self.broadcasters)} 个发送端广播 new_viewer")
            await asyncio.gather(
                *[client.send(message) for client in self.broadcasters],
                return_exceptions=True
            )
    
    async def unregister(self, websocket):
        """注销客户端"""
        if websocket in self.broadcasters:
            self.broadcasters.remove(websocket)
            logger.info(f"发送端已断开，当前数量: {len(self.broadcasters)}")
        elif websocket in self.viewers:
            self.viewers.remove(websocket)
            logger.info(f"接收端已断开，当前数量: {len(self.viewers)}")
    
    async def handle_connection(self, websocket):
        """统一处理连接 - 通过查询参数 role 区分客户端类型"""
        try:
            # 获取 role 参数（兼容不同 websockets 版本）
            parsed = urlparse(websocket.request.path)
            query_params = parse_qs(parsed.query)
            logger.info(f"query_params={query_params}")
            role = query_params.get('role')[0]
            logger.info(f"新连接，role={role}")

            if role == 'broadcaster':
                await self.handle_broadcaster(websocket)
            elif role == 'viewer':
                await self.handle_viewer(websocket)
            elif role == 'status':
                await self.handle_status(websocket)
            else:
                logger.warning(f"未知角色: {role}，作为 viewer 处理")
                await self.handle_viewer(websocket)

        except Exception as e:
            logger.error(f"处理连接出错: {e}", exc_info=True)  # 打印完整堆栈
        finally:
            await self.unregister(websocket)
    
    async def handle_broadcaster(self, websocket):
        """处理发送端消息"""
        try:
            await self.register_broadcaster(websocket)
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')
                    
                    logger.info(f"发送端消息: {msg_type}")
                    
                    if msg_type == 'offer':
                        # 转发offer给所有接收端
                        if self.viewers:
                            logger.info(f"转发offer给 {len(self.viewers)} 个接收端")
                            await asyncio.gather(
                                *[client.send(json.dumps({
                                    'type': 'offer',
                                    'sdp': data['sdp']
                                })) for client in self.viewers],
                                return_exceptions=True
                            )
                    
                    elif msg_type == 'ice_candidate':
                        # 转发ICE候选给所有接收端
                        if self.viewers:
                            await asyncio.gather(
                                *[client.send(json.dumps({
                                    'type': 'ice_candidate',
                                    'candidate': data['candidate']
                                })) for client in self.viewers],
                                return_exceptions=True
                            )
                except json.JSONDecodeError:
                    logger.error(f"无效的JSON消息: {message}")
                        
        except websockets.exceptions.ConnectionClosed:
            logger.info("发送端连接关闭")
    
    async def handle_viewer(self, websocket):
        """处理接收端消息"""
        try:
            await self.register_viewer(websocket)
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')
                    
                    logger.info(f"接收端消息: {msg_type}")
                    
                    if msg_type == 'answer':
                        # 转发answer给所有发送端
                        if self.broadcasters:
                            logger.info(f"转发answer给 {len(self.broadcasters)} 个发送端")
                            await asyncio.gather(
                                *[client.send(json.dumps({
                                    'type': 'answer',
                                    'sdp': data['sdp']
                                })) for client in self.broadcasters],
                                return_exceptions=True
                            )
                    
                    elif msg_type == 'ice_candidate':
                        # 转发ICE候选给所有发送端
                        if self.broadcasters:
                            await asyncio.gather(
                                *[client.send(json.dumps({
                                    'type': 'ice_candidate',
                                    'candidate': data['candidate']
                                })) for client in self.broadcasters],
                                return_exceptions=True
                            )
                    
                    elif msg_type == 'viewer_ready':
                        # 接收端就绪消息
                        logger.info(f"接收端就绪: {data}")
                        # 通知发送端有新viewer
                        if self.broadcasters:
                            message = json.dumps({'type': 'new_viewer', 'message': '有新的观看者连接'})
                            await asyncio.gather(
                                *[client.send(message) for client in self.broadcasters],
                                return_exceptions=True
                            )
                            
                except json.JSONDecodeError:
                    logger.error(f"无效的JSON消息: {message}")
                            
        except websockets.exceptions.ConnectionClosed:
            logger.info("接收端连接关闭")
    
    async def handle_status(self, websocket):
        """处理状态查询"""
        try:
            await websocket.send(json.dumps({
                'type': 'status',
                'broadcasters': len(self.broadcasters),
                'viewers': len(self.viewers)
            }))
        finally:
            await websocket.close()

async def main():
    server = SignalingServer()
    
    # 使用同一个服务器，通过路径区分
    async with websockets.serve(
        server.handle_connection,   # 注意：这里只传函数名，不再有 path 参数
        "0.0.0.0",
        8765,
        ping_interval=20,
        ping_timeout=60
    ):
        logger.info("=" * 60)
        logger.info("信令服务器启动成功")
        logger.info(f"服务器地址: ws://0.0.0.0:8765")
        logger.info("-" * 60)
        logger.info("路径说明:")
        logger.info("  - 发送端: ws://localhost:8765/broadcaster")
        logger.info("  - 接收端: ws://localhost:8765/viewer")
        logger.info("  - 状态查询: ws://localhost:8765/status")
        logger.info("=" * 60)
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())