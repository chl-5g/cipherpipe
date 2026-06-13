# CipherPipe

端到端加密数据传输管道。基于 Nostr 协议，无需中心服务器。人类、AI agent、外部系统平等接入。

## 设计哲学

**CipherPipe 是一根管子。** 管子里流什么、谁在流，管子自己不知道。

三个核心约束：
1. **服务器零知识** — relay 只转发加密 blob，永不解密
2. **参与者平等** — 人类浏览器、AI agent、外部脚本，对 relay 来说都是两个公钥在互发加密事件
3. **无单点故障** — 同时连多个 Nostr relay，挂一个自动切另一个，不通 IP、不依赖单一实体

## 架构

```
                    Nostr Relay 网络 (全球公共)
                   /    |    \    ...  (同时连3+个relay)
                  /     |     \
         ┌──────────┐  ┌──────────┐  ┌──────────┐
         │  proxy.py │  │  cli.py  │  │  cli.py  │
         │ (机器 A)   │  │ (机器 B)  │  │ (VPS 海外)│
         └────┬─────┘  └──────────┘  └──────────┘
              │
    ┌─────────┴──────────┐
    │                    │
  Browser            LAN WS (:8702)
  (:8701)            本地直连通道

  plaintext WS       LAN fast-path
  浏览器明文对话       Agent间直连(毫秒级)
  不持有密钥          trusted network
```

### 三层传输

| 层 | 端口 | 延迟 | 用途 |
|----|------|------|------|
| **Nostr relay 池** | (公共) | 200-500ms | 跨网络、跨地域。加密事件通过全球 relay 转发 |
| **LAN WebSocket** | 8702 | <1ms | 同一局域网 agent 直连。毫秒级，不经过 relay |
| **Browser proxy** | 8701 | <1ms (本地) | 浏览器 ↔ proxy 明文。密钥只存 proxy，浏览器不碰 |

### 路由策略

agent 发消息时：
1. 先检查目标是否在局域网可达 → 走 LAN WS，毫秒级
2. 不可达 → 走 Nostr relay 池，全球可达

### 加密模型

- **协议**: NIP-44 (XChaCha20-Poly1305)
- **密钥交换**: ECDH（secp256k1 椭圆曲线）
- **会话密钥派生**: HKDF(salt="nip44-v2")
- **事件签名**: BIP-340 Schnorr（coincurve/secp256k1）
- **每条消息**：独立随机 nonce，防重放
- **防篡改**：ChaCha20-Poly1305 认证加密，密文被改自动检测

### 密钥管理

| 组件 | 持有密钥 | 职责 |
|------|---------|------|
| proxy.py | Nostr 私钥 (nostr.key) | 签名事件、NIP-44 加解密、转发给浏览器 |
| cli.py | 自己的私钥 | 直连 Nostr relay，自行加解密 |
| Browser | 无 | 只收发明文。密钥不进入浏览器 |
| Nostr relay | 无 | 只转发签名事件，不解密 |

### 为什么不需要自己的服务器

Nostr 全球有几千个公共 relay。CipherPipe 启动时向所有 relay 开持久 WebSocket，同一条连接上收发所有事件——不发新连接，不重握手，消息来了即时推送。relay 之间不互相同步，靠客户端向多个 relay 同时发布保证到达。

不依赖单一 relay，不存在"服务器宕机"——挂了一个，其他的继续跑。

## 快速开始

```bash
pip install -r requirements.txt
python proxy.py
```

浏览器打开 `http://localhost:8701`。

### 一键启动

```bash
bash run.sh
```

### CLI（AI Agent 模式）

```bash
# 生成身份、连 relay、监听消息、agent 推理后回复
python cli.py --peer <对方公钥> --name agent_0.11 --no-stdin
```

## 使用场景

### 1. 人类 ↔ 人类加密聊天

两个人在各自的浏览器上，互填对方公钥。消息 NIP-44 加密，Nostr relay 全球转发，无中心服务器。任何第三方看不到内容。

### 2. 人类 ↔ AI Agent 对话

人在浏览器，agent 在终端跑 `cli.py --no-stdin`。从 Nostr 的角度看，两者没有区别——两个公钥互发加密 DM。人在聊天框问，agent 解密后推理、加密回复。

### 3. Agent ↔ Agent 协作

两台机器上各跑一个 agent，通过 CipherPipe 加密通信——和之前 0.10↔0.11 的 agent-bridge 一样，但现在是端到端加密、全球 relay 网络、去中心化。

### 4. 跨网络 API 中转

```
用户(国内)──Nostr加密──→ 海外Agent──调API──→结果加密返回
```

国内节点不持有海外 API key。加密管道透明运输，relay 看不到内容。不是 VPN（不代理 TCP），但能做应用层信息中转。

### 5. 局域网即时通信

同一局域网内 agent 之间走 LAN WebSocket 直连，毫秒延迟。不比在内网直接发 HTTP 慢。配合 Nostr 跨网兜底，自动降级。

## 协议细节

### Nostr 事件格式

```json
{
  "kind": 4,
  "content": "<NIP-44 encrypted base64>",
  "tags": [["p", "<recipient pubkey>"]],
  "pubkey": "<sender pubkey>",
  "sig": "<Schnorr signature>"
}
```

- `kind: 4` = 加密 DM
- `content` = NIP-44 XChaCha20-Poly1305 加密后的 base64
- `tags` = 收件人公钥列表
- `sig` = 发送者对事件 ID 的 BIP-340 Schnorr 签名

### 浏览器 ↔ proxy 协议

纯 WebSocket JSON（明文，本地环回）：

```json
// 发送
{"type": "msg", "text": "hello", "to": "<peer pubkey>"}

// 接收
{"type": "msg", "from": "abc123...", "text": "hello back"}
{"type": "identity", "pubkey": "abc123..."}
```

### LAN 直连协议

纯 WebSocket JSON（明文，受信内网）：

```
ws://<机器IP>:8702

// 发送
{"type": "msg", "text": "hello"}

// 接收
{"type": "msg", "from": "lan", "text": "hello"}
```

## 项目结构

```
cipherpipe/
  proxy.py          # Nostr 客户端桥 + LAN 直连 + 浏览器入口 (:8701/:8702)
  cli.py            # Nostr CLI (人类/Agent 通用)
  dashboard.html    # 浏览器聊天 UI (零加密逻辑)
  run.sh            # 一键启动
  requirements.txt  # Python 依赖
  nostr.key         # Nostr 私钥 (自动生成, .gitignore)
  logs/             # 结构化日志 (JSONL)
  archive/          # 旧版文件 (server.py/db.py/crypto_room.py)
```

## 依赖

| 包 | 用途 |
|----|------|
| `coincurve` | secp256k1, BIP-340 Schnorr 签名 |
| `cryptography` | XChaCha20-Poly1305, ECDH, HKDF (NIP-44) |
| `websockets` | Nostr relay 持久连接 + LAN WS + 浏览器 proxy |
| `structlog` | 结构化日志 (控制台 + JSONL 文件) |

## 许可证

MIT
