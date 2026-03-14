# broadcaster.py
import asyncio
import json
import websockets
from webrtc_video_source import WebRTCWithVideoSource
from aiortc import RTCSessionDescription
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebRTCBroadcaster:
    """
    WebRTC视频发送端 - 连接到信令服务器
    """
    
    def __init__(self, video_path, signaling_server="ws://localhost:8765/?role=broadcaster"):
        self.video_path = video_path
        self.signaling_server = signaling_server
        self.webrtc = None
        self.websocket = None
        self.running = True
        
    # 修改 broadcaster.py 中的连接部分
    async def connect_to_signaling_server(self):
        """连接到信令服务器"""
        try:
            logger.info(f"正在连接到信令服务器: {self.signaling_server}")
        
            server_url = self.signaling_server
            self.websocket = await websockets.connect(
                server_url,
                ping_interval=None,
                max_size=2**20
            )
            logger.info("已连接到信令服务器")
            
            # 启动消息处理
            asyncio.create_task(self.handle_signaling_messages())
            
            return True
        except Exception as e:
            logger.error(f"连接信令服务器失败: {e}")
            return False
    
    async def handle_signaling_messages(self):
        """处理信令消息"""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                msg_type = data.get('type')
                
                logger.info(f"收到信令消息: {msg_type}")
                
                if msg_type == 'answer':
                    # 收到viewer的answer
                    if self.webrtc and self.webrtc.pc:
                        sdp = data['sdp']
                        await self.webrtc.pc.setRemoteDescription(
                            RTCSessionDescription(sdp=sdp['sdp'], type=sdp['type'])
                        )
                        logger.info("已设置远程描述")
                
                elif msg_type == 'ice_candidate':
                    # 收到ICE候选
                    if self.webrtc and self.webrtc.pc:
                        await self.webrtc.pc.addIceCandidate(data['candidate'])
                        logger.info("已添加ICE候选")
                
                elif msg_type == 'new_viewer':
                    logger.info("收到 new_viewer 消息，准备重新发送 offer")
                    await self.send_offer()
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("信令服务器连接关闭")
            self.running = False
        except Exception as e:
            logger.error(f"处理信令消息出错: {e}")
    
    async def send_offer(self):
        """创建并发送offer"""
        try:
            if not self.webrtc:
                logger.info("创建视频WebRTC连接...")
                self.webrtc = WebRTCWithVideoSource(self.video_path)
                
                # 设置ICE候选处理（仅一次）
                @self.webrtc.pc.on("icecandidate")
                async def on_icecandidate(candidate):
                    if candidate and self.websocket:
                        logger.info(f"生成ICE候选: {candidate.candidate[:50]}...")  # 添加日志
                        await self.websocket.send(json.dumps({
                            'type': 'ice_candidate',
                            'candidate': {
                                'candidate': candidate.candidate,
                                'sdpMid': candidate.sdpMid,
                                'sdpMLineIndex': candidate.sdpMLineIndex
                            }
                        }))
                
                # 初次设置连接（创建数据通道、添加轨道）
                await self.webrtc.setup_connection()
            else:
                logger.info("WebRTC已存在，直接创建新offer")
                # 创建新offer
                offer = await self.webrtc.pc.createOffer()
                await self.webrtc.pc.setLocalDescription(offer)

            # 发送offer（注意使用 self.webrtc.pc.localDescription）
            await self.websocket.send(json.dumps({
                'type': 'offer',
                'sdp': {
                    'sdp': self.webrtc.pc.localDescription.sdp,
                    'type': self.webrtc.pc.localDescription.type
                }
            }))
            logger.info("已发送offer")

        except Exception as e:
            logger.error(f"发送offer失败: {e}", exc_info=True)  # 输出完整堆栈
    
    async def start_broadcasting(self):
        """开始广播"""
        # 连接信令服务器
        if not await self.connect_to_signaling_server():
            logger.error("无法连接到信令服务器")
            return
        
        # 发送offer
        await self.send_offer()
        
        # 启动元数据发送任务
        if self.webrtc:
            asyncio.create_task(self.periodic_metadata_send())
        
        # 保持运行
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("停止广播")
        finally:
            await self.cleanup()
    
    async def periodic_metadata_send(self):
        """定期发送元数据"""
        while self.running and self.webrtc:
            try:
                await self.webrtc.periodic_metadata_send()
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"发送元数据失败: {e}")
                break
    
    async def cleanup(self):
        """清理资源"""
        logger.info("清理资源...")
        if self.webrtc:
            self.webrtc.release()
        if self.websocket:
            await self.websocket.close()
        logger.info("清理完成")

async def main():
    # 使用默认视频文件，如果没有则使用模拟视频
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    # 拼接视频文件的绝对路径
    video_file_name = "test_video.mp4"
    video_abs_path = os.path.join(current_script_dir, 'data',video_file_name)
    broadcaster = WebRTCBroadcaster(video_abs_path)
    await broadcaster.start_broadcasting()

if __name__ == "__main__":
    asyncio.run(main())