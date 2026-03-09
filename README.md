# wechat-sdk-qclaw

QChat WeChat 聊天机器人 SDK — 类 ItChat 风格 API，基于 OpenClaw 后端。

## 安装

```bash
pip install wechat-sdk-qclaw

# 可选：终端二维码显示
pip install wechat-sdk-qclaw[qrcode]
```

## 快速开始

### 实例模式

```python
from qclaw import QChat, content

bot = QChat()

@bot.msg_register(content.TEXT)
def echo(msg):
    return f"Echo: {msg.text}"

bot.auto_login()
bot.run()
```

### 模块级单例模式 (ItChat 风格)

```python
import qclaw

@qclaw.msg_register(qclaw.content.TEXT)
def echo(msg):
    return f"Echo: {msg.text}"

qclaw.auto_login()
qclaw.run()
```

## 流式回复

处理函数接受两个参数时，第二个参数为 `ReplyContext`，支持流式发送文本块和工具调用状态：

```python
@bot.msg_register(content.TEXT)
async def stream_reply(msg, reply):
    # 发送流式文本块
    await reply.send_chunk("正在处理...")

    # 工具调用
    handle = reply.tool_call("搜索中")
    await handle.update("找到 3 条结果")
    await handle.complete("搜索完成")

    await reply.send_chunk("处理完毕！")
    return "最终回复文本"
```

## 环境切换

```python
# 使用测试环境
bot = QChat(env="test")

# 或者自定义配置
from qclaw import Config
bot = QChat(config=Config(
    env="production",
    heartbeat_interval=30.0,
    reconnect_interval=5.0,
))
```

## 消息对象

处理函数接收的 `msg` 对象包含以下属性：

| 属性 | 类型 | 说明 |
|------|------|------|
| `msg.text` | `str` | 消息文本内容 |
| `msg.user_id` | `str` | 发送者用户 ID |
| `msg.session_id` | `str` | 会话 ID |
| `msg.prompt_id` | `str` | 当前轮次 ID |
| `msg.guid` | `str` | 发送者设备 GUID |
| `msg.type` | `str` | 消息类型 |
| `msg.raw` | `dict` | 原始 AGP 协议信封 |

## API 参考

### `QChat`

- `QChat(env="production", config=None)` — 创建机器人实例
- `bot.msg_register(msg_type)` — 注册消息处理装饰器
- `bot.auto_login(hot_reload=True)` — 微信扫码登录
- `bot.run(block=True)` — 启动事件循环
- `bot.stop()` — 停止机器人
- `bot.logout()` — 清除登录态

### 处理函数签名

```python
# 简单模式：接收消息，返回字符串回复
def handler(msg: Message) -> str: ...

# 流式模式：接收消息和回复上下文
async def handler(msg: Message, reply: ReplyContext) -> str | None: ...
```

同步和异步处理函数均可使用。

## 依赖

- `httpx>=0.25` — HTTP 客户端
- `websockets>=12.0` — WebSocket 客户端
- `qrcode[pil]` (可选) — 终端二维码显示

## License

MIT
