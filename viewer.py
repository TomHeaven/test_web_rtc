# viewer.py (修改后的版本，增加更详细的日志)
import asyncio
import json
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
import cv2
import numpy as np
import logging
import os
import sys
import time

# 设置日志级别
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 在导入 cv2 之前设置环境变量
os.environ['QT_QPA_PLATFORM'] = 'xcb'

# 或者使用不同的 OpenCV 后端
cv2.setNumThreads(0)  # 禁用多线程

class WebRTCViewer:
    """
    WebRTC视频接收端 - 连接到信令服务器
    """
    
    def __init__(self, signaling_server):
        self.signaling_server = signaling_server
        self.pc = None
        self.websocket = None
        self.running = True
        self.video_track = None
        self.connected = False
        
        logger.info(f"初始化Viewer，信令服务器: {signaling_server}")
        
        logger.warning(f"无法创建GUI窗口，将只保存视频帧")
        self.use_gui = False
        
        # 存储接收到的元数据
        self.target_positions = []
        self.drone_telemetry = {}
        self.tracking_info = {}
        self.frame_count = 0
        
    # 修改 viewer.py 中的连接部分
    async def connect_to_signaling_server(self):
        """连接到信令服务器"""
        try:
            logger.info(f"正在连接到信令服务器: {self.signaling_server}")
            # 添加路径 /viewer
            if not self.signaling_server.endswith('/viewer'):
                server_url = self.signaling_server + '/viewer'
            else:
                server_url = self.signaling_server
                
            self.websocket = await websockets.connect(
                server_url,
                ping_interval=None,
                max_size=2**20  # 增加消息大小限制
            )
            logger.info("已连接到信令服务器")
            self.connected = True
            
            # 启动消息处理
            asyncio.create_task(self.handle_signaling_messages())
            
            # 发送一个初始化消息
            await self.websocket.send(json.dumps({
                'type': 'viewer_ready',
                'timestamp': time.time()
            }))
            logger.info("已发送初始化消息")
            
            return True
        except Exception as e:
            logger.error(f"连接信令服务器失败: {e}")
            return False
    
    def setup_peer_connection(self):
        """创建RTCPeerConnection"""
        logger.info("创建RTCPeerConnection...")
        self.pc = RTCPeerConnection()
        
        @self.pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate and self.websocket and self.connected:
                logger.debug(f"发送ICE候选: {candidate}")
                await self.websocket.send(json.dumps({
                    'type': 'ice_candidate',
                    'candidate': {
                        'candidate': candidate.candidate,
                        'sdpMid': candidate.sdpMid,
                        'sdpMLineIndex': candidate.sdpMLineIndex
                    }
                }))
        
        @self.pc.on("track")
        def on_track(track):
            logger.info(f"收到轨道: {track.kind}")
            if track.kind == "video":
                self.video_track = track
                asyncio.create_task(self.process_video(track))
        
        @self.pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(f"收到数据通道: {channel.label}")
            self.setup_data_channel(channel)
        
        @self.pc.on("iceconnectionstatechange")
        def on_iceconnectionstatechange():
            logger.info(f"ICE连接状态: {self.pc.iceConnectionState}")
        
        @self.pc.on("connectionstatechange")
        def on_connectionstatechange():
            logger.info(f"连接状态: {self.pc.connectionState}")
    
    def setup_data_channel(self, channel):
        """配置数据通道"""
        logger.info(f"配置数据通道: {channel.label}")
        
        @channel.on("message")
        def on_message(message):
            try:
                if isinstance(message, str):
                    data = json.loads(message)
                else:
                    data = json.loads(message.decode('utf-8'))
                
                data_type = data.get('type')
                logger.debug(f"数据通道消息: {data_type}")
                
                if data_type == 'target_position':
                    self.target_positions.append({
                        'timestamp': data.get('timestamp'),
                        'position': data.get('position'),
                        'confidence': data.get('confidence', 1.0)
                    })
                    if len(self.target_positions) > 100:
                        self.target_positions = self.target_positions[-100:]
                    logger.debug(f"目标位置: {data.get('position')}")
                    
                elif data_type == 'drone_telemetry':
                    self.drone_telemetry = data
                    logger.debug(f"遥测数据: {data}")
                    
                elif data_type == 'tracking_info':
                    self.tracking_info = data
                    logger.debug(f"跟踪信息: {data}")
                    
            except Exception as e:
                logger.error(f"处理数据通道消息出错: {e}")
    
    async def handle_signaling_messages(self):
        """处理信令消息"""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                msg_type = data.get('type')
                
                logger.info(f"收到信令消息: {msg_type}")
                
                if msg_type == 'offer':
                    await self.handle_offer(data)
                    
                elif msg_type == 'ice_candidate':
                    if self.pc:
                        logger.debug(f"添加ICE候选")
                        await self.pc.addIceCandidate(data['candidate'])
                    
                elif msg_type == 'status':
                    logger.info(f"服务器状态: {data}")
                        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("信令服务器连接关闭")
            self.connected = False
            self.running = False
        except Exception as e:
            logger.error(f"处理信令消息出错: {e}")
            self.connected = False
    
    async def handle_offer(self, data):
        """处理收到的offer并发送answer"""
        try:
            logger.info("处理offer，创建PeerConnection...")
            # 初始化PeerConnection
            if not self.pc:
                self.setup_peer_connection()
            
            # 设置远程描述（offer）
            offer_sdp = data.get('sdp')
            # 兼容broadcaster的SDP格式（修复嵌套问题）
            if isinstance(offer_sdp, dict) and 'sdp' in offer_sdp and 'type' in offer_sdp:
                # 处理broadcaster的嵌套SDP
                remote_desc = RTCSessionDescription(
                    sdp=offer_sdp['sdp'],
                    type=offer_sdp['type']
                )
            else:
                # 兼容普通SDP格式
                remote_desc = RTCSessionDescription(
                    sdp=offer_sdp,
                    type='offer'
                )
            
            await self.pc.setRemoteDescription(remote_desc)
            logger.info("已设置远程offer")
            
            # 创建answer
            answer = await self.pc.createAnswer()
            await self.pc.setLocalDescription(answer)
            logger.info("已创建并设置local answer")
            
            # 发送answer给信令服务器
            await self.websocket.send(json.dumps({
                'type': 'answer',
                'sdp': {
                    'sdp': self.pc.localDescription.sdp,
                    'type': self.pc.localDescription.type
                }
            }))
            logger.info("已发送answer")
            
        except Exception as e:
            logger.error(f"处理offer失败: {e}", exc_info=True)
    
    async def process_video(self, track):
        """处理视频帧（异步）"""
        logger.info("开始处理视频流")
        while self.running and self.connected:
            try:
                frame = await track.recv()
                self.frame_count += 1
                if self.frame_count % 30 == 0:
                    logger.info(f"已接收 {self.frame_count} 帧视频")
                
                # 保存帧到本地（替代GUI显示）
                if not self.use_gui:
                    img = frame.to_ndarray(format="bgr24")
                    #cv2.imwrite(f"received_frame_{self.frame_count}.jpg", img)
                    
            except Exception as e:
                logger.error(f"处理视频帧出错: {e}")
                break
        logger.info("视频流处理结束")
    
    def draw_metadata(self, img):
        """在图像上绘制元数据"""
        h, w = img.shape[:2]
        
        # 绘制目标位置
        if self.target_positions:
            latest = self.target_positions[-1]
            x, y = latest['position']
            confidence = latest['confidence']
            
            # 根据置信度选择颜色
            if confidence > 0.8:
                color = (0, 0, 255)  # 红色
            elif confidence > 0.5:
                color = (0, 255, 255)  # 黄色
            else:
                color = (255, 0, 0)  # 蓝色
            
            # 绘制目标框
            cv2.rectangle(img, (x-30, y-30), (x+30, y+30), color, 2)
            cv2.circle(img, (x, y), 5, color, -1)
            
            # 显示坐标
            cv2.putText(img, f"Target: ({x}, {y})", (x+40, y-40),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            cv2.putText(img, f"Conf: {confidence:.2f}", (x+40, y-20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        
        # 显示遥测数据
        y_offset = 30
        if self.drone_telemetry:
            cv2.putText(img, f"Alt: {self.drone_telemetry.get('altitude', 0):.1f}m", 
                       (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            y_offset += 20
            cv2.putText(img, f"Speed: {self.drone_telemetry.get('speed', 0):.1f}m/s", 
                       (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            y_offset += 20
            cv2.putText(img, f"Battery: {self.drone_telemetry.get('battery', 0):.1f}%", 
                       (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # 显示跟踪信息
        if self.tracking_info:
            cv2.putText(img, f"Tracker: {self.tracking_info.get('algorithm', 'Unknown')}", 
                       (w - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(img, f"FPS: {self.tracking_info.get('fps', 0)}", 
                       (w - 200, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # 显示帧计数和连接状态
        cv2.putText(img, f"Frame: {self.frame_count}", 
                   (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # 显示连接状态
        status = "Connected" if self.connected else "Disconnected"
        color_status = (0, 255, 0) if self.connected else (0, 0, 255)
        cv2.putText(img, f"Status: {status}", 
                   (w - 150, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_status, 1)
        
        return img
    
    async def start(self):
        """开始接收视频"""
        logger.info("启动Viewer...")
        
        if not await self.connect_to_signaling_server():
            logger.error("无法连接到信令服务器")
            return
        
        logger.info("等待视频流...")
        
        # 保持运行
        try:
            while self.running:
                await asyncio.sleep(1)
                if not self.connected:
                    logger.warning("连接已断开，尝试重连...")
                    await asyncio.sleep(5)
                    if self.running:
                        await self.connect_to_signaling_server()
        except KeyboardInterrupt:
            logger.info("用户中断，停止接收")
        except Exception as e:
            logger.error(f"运行错误: {e}")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """清理资源"""
        logger.info("清理资源...")
        self.running = False
        if self.pc:
            await self.pc.close()
        if self.websocket:
            await self.websocket.close()
        cv2.destroyAllWindows()
        logger.info("清理完成")

async def main():
    # 使用命令行参数或环境变量设置信令服务器地址
    import os
    import sys
    
    # 默认使用端口8766（接收端专用端口）
    signaling_server = os.environ.get('SIGNALING_SERVER', 'ws://localhost:8765/?role=viewer')
    
    # 如果提供了命令行参数
    if len(sys.argv) > 1:
        signaling_server = sys.argv[1]
    
    logger.info(f"使用信令服务器: {signaling_server}")
    
    viewer = WebRTCViewer(signaling_server)
    await viewer.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序错误: {e}")