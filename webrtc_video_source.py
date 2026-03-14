# webrtc_video_source.py
import asyncio
import json
import time
import cv2
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaBlackhole, MediaPlayer
import av
import random
from fractions import Fraction
from pathlib import Path

class VideoFileSource:
    """
    视频文件源，支持读取本地视频文件并提供模拟目标位置
    """
    
    def __init__(self, video_path, loop_video=True):
        """
        初始化视频源
        
        Args:
            video_path: 视频文件路径
            loop_video: 是否循环播放视频
        """
        self.video_path = video_path
        self.loop_video = loop_video
        self.cap = None
        self.fps = 30
        self.frame_width = 1280
        self.frame_height = 720
        self.total_frames = 0
        self.current_frame = 0
        
        # 目标模拟相关
        self.simulate_target = True
        self.target_position = [640, 360]  # 初始目标位置（图像中心）
        self.target_speed = [2, 1.5]  # 目标移动速度 [x_speed, y_speed]
        self.target_size = 50  # 目标大小（像素）
        self.target_color = (0, 0, 255)  # BGR红色
        
        # 轨迹模拟
        self.trajectory_type = 'circle'  # circle, sine, random
        self.trajectory_params = {
            'circle': {'radius': 200, 'center': [640, 360], 'angle': 0},
            'sine': {'amplitude': 150, 'frequency': 0.02, 'center_x': 640, 'center_y': 360},
            'random': {'bounds': [100, 1180, 100, 620], 'direction': [3, 2]}
        }
        
        self._open_video()
    
    def _open_video(self):
        """打开视频文件"""
        if not Path(self.video_path).exists():
            print(f"警告: 视频文件 {self.video_path} 不存在，将使用模拟视频")
            self._create_simulated_video()
        else:
            self.cap = cv2.VideoCapture(self.video_path)
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            print(f"视频信息: {self.frame_width}x{self.frame_height}, {self.fps}fps, {self.total_frames}帧")
    
    def _create_simulated_video(self):
        """创建模拟视频（当视频文件不存在时）"""
        print("使用模拟视频生成器")
        self.cap = None
        self.fps = 30
        self.frame_width = 1280
        self.frame_height = 720
        self.total_frames = 0
        self.simulate_mode = True
    
    def get_frame(self):
        """获取下一帧图像"""
        if hasattr(self, 'simulate_mode') and self.simulate_mode:
            return self._generate_simulated_frame()
        
        if self.cap is None:
            return None
        
        ret, frame = self.cap.read()
        
        if not ret and self.loop_video:
            # 循环播放视频
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()
        
        if ret:
            self.current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        
        return frame if ret else None
    
    def _generate_simulated_frame(self):
        """生成模拟视频帧"""
        # 创建渐变背景
        frame = np.zeros((self.frame_height, self.frame_width, 3), dtype=np.uint8)
        for i in range(self.frame_height):
            color = int(128 + 127 * np.sin(i / 50))
            frame[i, :] = [color, color, color]
        
        # 添加网格线
        for x in range(0, self.frame_width, 100):
            cv2.line(frame, (x, 0), (x, self.frame_height), (100, 100, 100), 1)
        for y in range(0, self.frame_height, 100):
            cv2.line(frame, (0, y), (self.frame_width, y), (100, 100, 100), 1)
        
        # 添加时间戳
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, f"Simulated Video - {timestamp}", 
                   (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        
        return frame
    
    def update_target_position(self):
        """更新模拟目标位置"""
        if not self.simulate_target:
            return self.target_position
        
        if self.trajectory_type == 'circle':
            # 圆形轨迹
            params = self.trajectory_params['circle']
            params['angle'] += 0.05
            x = int(params['center'][0] + params['radius'] * np.cos(params['angle']))
            y = int(params['center'][1] + params['radius'] * np.sin(params['angle']))
            self.target_position = [x, y]
            
        elif self.trajectory_type == 'sine':
            # 正弦轨迹
            params = self.trajectory_params['sine']
            self.target_position[0] += 2
            if self.target_position[0] > self.frame_width - 100:
                self.target_position[0] = 100
            self.target_position[1] = int(params['center_y'] + 
                                         params['amplitude'] * np.sin(params['frequency'] * self.target_position[0]))
            
        elif self.trajectory_type == 'random':
            # 随机反弹轨迹
            params = self.trajectory_params['random']
            self.target_position[0] += params['direction'][0]
            self.target_position[1] += params['direction'][1]
            
            # 边界反弹
            if self.target_position[0] <= params['bounds'][0] or self.target_position[0] >= params['bounds'][1]:
                params['direction'][0] *= -1
            if self.target_position[1] <= params['bounds'][2] or self.target_position[1] >= params['bounds'][3]:
                params['direction'][1] *= -1
        
        return self.target_position
    
    def draw_target(self, frame, target_pos, confidence=1.0):
        """在帧上绘制目标位置"""
        if frame is None:
            return frame
        
        x, y = target_pos
        
        # 根据置信度调整颜色
        if confidence > 0.8:
            color = (0, 0, 255)  # 红色 - 高置信度
        elif confidence > 0.5:
            color = (0, 255, 255)  # 黄色 - 中置信度
        else:
            color = (255, 0, 0)  # 蓝色 - 低置信度
        
        # 绘制目标框
        size = self.target_size
        cv2.rectangle(frame, (x - size//2, y - size//2), 
                     (x + size//2, y + size//2), color, 2)
        
        # 绘制十字准星
        cv2.line(frame, (x - 20, y), (x + 20, y), color, 1)
        cv2.line(frame, (x, y - 20), (x, y + 20), color, 1)
        
        # 绘制中心点
        cv2.circle(frame, (x, y), 5, color, -1)
        
        # 显示坐标和置信度
        cv2.putText(frame, f"Target: ({x}, {y}) conf:{confidence:.2f}", 
                   (x + 30, y - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        return frame
    
    def release(self):
        """释放资源"""
        if self.cap is not None:
            self.cap.release()


class VideoStreamTrackWithTarget(VideoStreamTrack):
    """
    带有模拟目标位置的视频轨道
    """
    
    def __init__(self, video_source):
        super().__init__()
        self.video_source = video_source
        self.frame_count = 0
        self.metadata_buffer = {}
        self.target_history = []  # 保存目标位置历史
        
    async def recv(self):
        """接收视频帧，包含模拟目标"""
        
        # 获取视频帧
        frame = self.video_source.get_frame()
        
        if frame is None:
            # 如果没有帧，创建黑色帧
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        
        # 更新目标位置
        target_pos = self.video_source.update_target_position()
        
        # 模拟检测置信度（可以随时间变化）
        confidence = 0.7 + 0.3 * np.sin(self.frame_count * 0.1)
        
        # 在帧上绘制目标
        frame = self.video_source.draw_target(frame, target_pos, confidence)
        
        # 保存目标位置历史
        self.target_history.append({
            'frame_id': self.frame_count,
            'position': target_pos,
            'timestamp': time.time(),
            'confidence': confidence
        })
        
        # 限制历史记录长度
        if len(self.target_history) > 1000:
            self.target_history = self.target_history[-1000:]
        
        # 存储当前帧的元数据
        self.metadata_buffer[self.frame_count] = {
            'timestamp': time.time(),
            'frame_id': self.frame_count,
            'target_position': target_pos,
            'target_confidence': confidence
        }
        
        # 转换为VideoFrame
        video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = self.frame_count
        video_frame.time_base = Fraction(1, 30)
        
        self.frame_count += 1
        return video_frame
    
    def get_frame_metadata(self, frame_id):
        """获取指定帧的元数据"""
        return self.metadata_buffer.get(frame_id)
    
    def get_latest_target(self):
        """获取最新的目标位置"""
        if self.target_history:
            return self.target_history[-1]
        return None


class WebRTCWithVideoSource:
    """
    使用视频文件源的WebRTC连接
    """
    
    def __init__(self, video_path):
        self.pc = RTCPeerConnection()
        self.video_source = VideoFileSource(video_path)
        self.video_track = VideoStreamTrackWithTarget(self.video_source)
        self.data_channel = None
        self.metadata_channel = None
        
        # 存储各种元数据
        self.target_positions = []
        self.drone_telemetry = {}
        self.tracking_info = {}
        
    async def setup_connection(self):
        """建立WebRTC连接"""
        
        # 1. 主数据通道 - 用于控制命令
        self.data_channel = self.pc.createDataChannel("control")
        self._setup_data_channel(self.data_channel, "control")
        
        # 2. 元数据通道 - 用于传输跟踪信息和遥测数据
        self.metadata_channel = self.pc.createDataChannel("metadata")
        self._setup_data_channel(self.metadata_channel, "metadata")
        
        # 3. 添加视频轨道
        self.pc.addTrack(self.video_track)
        
        # 处理传入的数据通道
        @self.pc.on("datachannel")
        def on_datachannel(channel):
            print(f"收到数据通道: {channel.label}")
            self._setup_data_channel(channel, channel.label)
        
        # 创建offer
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        
        return offer
    
    def _setup_data_channel(self, channel, channel_type):
        """配置数据通道"""
        
        @channel.on("open")
        def on_open():
            print(f"数据通道 '{channel_type}' 已打开")
            
        @channel.on("message")
        def on_message(message):
            self._handle_metadata(message, channel_type)
            
        @channel.on("close")
        def on_close():
            print(f"数据通道 '{channel_type}' 已关闭")
    
    def _handle_metadata(self, message, channel_type):
        """处理接收到的元数据"""
        try:
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = json.loads(message.decode('utf-8'))
            
            if channel_type == "metadata":
                self._process_metadata(data)
            elif channel_type == "control":
                self._process_control(data)
                
        except Exception as e:
            print(f"元数据处理错误: {e}")
    
    def _process_metadata(self, data):
        """处理元数据"""
        data_type = data.get('type')
        
        if data_type == 'target_position':
            self.target_positions.append({
                'timestamp': data.get('timestamp'),
                'position': data.get('position'),
                'confidence': data.get('confidence', 1.0)
            })
            print(f"收到目标位置: {data.get('position')}")
            
        elif data_type == 'drone_telemetry':
            self.drone_telemetry.update({
                'altitude': data.get('altitude'),
                'speed': data.get('speed'),
                'battery': data.get('battery'),
                'gps': data.get('gps')
            })
            
        elif data_type == 'tracking_info':
            self.tracking_info.update({
                'algorithm': data.get('algorithm'),
                'fps': data.get('fps'),
                'latency': data.get('latency')
            })
    
    def _process_control(self, data):
        """处理控制命令"""
        print(f"收到控制命令: {data}")
        
        # 可以添加控制命令处理逻辑
        command = data.get('command')
        if command == 'change_trajectory':
            trajectory_type = data.get('trajectory_type')
            if trajectory_type:
                self.video_source.trajectory_type = trajectory_type
                print(f"轨迹类型已更改为: {trajectory_type}")
        
        elif command == 'set_target_speed':
            speed = data.get('speed')
            if speed and len(speed) == 2:
                self.video_source.target_speed = speed
    
    async def send_metadata(self, metadata_type, metadata):
        """发送元数据"""
        if self.metadata_channel and self.metadata_channel.readyState == "open":
            message = {
                'type': metadata_type,
                'timestamp': time.time(),
                **metadata
            }
            self.metadata_channel.send(json.dumps(message))
    
    async def send_target_position(self, position, confidence=1.0):
        """发送目标位置元数据"""
        await self.send_metadata('target_position', {
            'position': position,
            'confidence': confidence
        })
    
    async def send_drone_telemetry(self, altitude, speed, battery, gps):
        """发送无人机遥测数据"""
        await self.send_metadata('drone_telemetry', {
            'altitude': altitude,
            'speed': speed,
            'battery': battery,
            'gps': gps
        })
    
    async def periodic_metadata_send(self):
        """定期发送元数据（模拟遥测数据）"""
        while True:
            if self.metadata_channel and self.metadata_channel.readyState == "open":
                # 获取最新的目标位置
                latest_target = self.video_track.get_latest_target()
                
                if latest_target:
                    # 发送目标位置
                    await self.send_target_position(
                        latest_target['position'],
                        latest_target['confidence']
                    )
                
                # 发送模拟的无人机遥测数据
                await self.send_drone_telemetry(
                    altitude=100 + 10 * np.sin(time.time()),  # 模拟高度变化
                    speed=15 + 5 * np.cos(time.time()),       # 模拟速度变化
                    battery=85 - time.time() % 3600 / 3600 * 10,  # 模拟电量下降
                    gps={"lat": 39.9, "lon": 116.3, "alt": 100}    # 固定GPS
                )
                
                # 发送跟踪信息
                await self.send_metadata('tracking_info', {
                    'algorithm': 'Simulated Tracker',
                    'fps': 30,
                    'latency': 0.05
                })
            
            await asyncio.sleep(0.1)  # 每100ms发送一次
    
    def release(self):
        """释放资源"""

        if self.video_track:
            self.video_track.stop()
            self.video_track = None
        
        # 关闭数据通道
        if self.data_channel and self.data_channel.readyState != "closed":
            self.data_channel.close()
        
        # 关闭peer connection
        if self.pc:
            # 创建一个任务来关闭连接，但不等待它
            asyncio.create_task(self._close_pc())
        
    def _close_pc(self):
        """异步关闭peer connection"""
        async def close():
            try:
                await self.pc.close()
            except Exception as e:
                print(f"关闭PeerConnection出错: {e}")
        
        return close()


# 使用示例
async def main():
    # 创建WebRTC连接，使用视频文件
    # 如果没有视频文件，会自动生成模拟视频
    webrtc = WebRTCWithVideoSource("~/Videos/DJI_20250719193051_0001_S.mp4")
    
    # 建立连接
    offer = await webrtc.setup_connection()
    print("WebRTC Offer 已创建")
    
    # 启动定期发送元数据的任务
    asyncio.create_task(webrtc.periodic_metadata_send())
    
    try:
        # 保持连接运行
        await asyncio.sleep(3600)  # 运行1小时
    finally:
        webrtc.release()


if __name__ == "__main__":
    # 运行示例
    asyncio.run(main())