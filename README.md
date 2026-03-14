# webRTC测试

## 安装依赖

```
pip install -r requierment.txt
```

## 启动服务
```
sh run.sh
```

脚本将启动： 
+ 信令服务：python signaling_server.py
+ 模拟视频服务：python broadcaster.py
+ 模拟接受端：web_client.html

## 查看效果：
打开http://localhost:8081,点击连接。
