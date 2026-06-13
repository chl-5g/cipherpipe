# CipherPipe

端到端加密数据传输管道。基于 Nostr 协议，无需中心服务器。

任何 client 平等接入，管道不关心谁在用。

## 设计哲学

**CipherPipe 是一根管子。** 管子里流什么、谁在流，管子自己不知道。

### 三个核心约束

1. **服务器零知识** — relay 只转发加密 blob，永不解密。管道不持有明文的任何时刻。
2. **参与者平等** — 对 relay 来说，所有 client 都是两个公钥在互发加密事件。没有角色区别，只有 senders 和 receivers。
3. **无单点故障** — 同时连多个 Nostr relay，挂一个自动切另一个。

### 管道不做什么

- **不调 LLM API**。AI 能力由外部进程注入，管道的职责是运输。
- **不持 API key**。加密是端到端的，管道中间不持有任何能解开内容的密钥。
- **不存明文**。消息落盘只存密文或本地明文缓存，relay 端永远是密文。

### 管道做什么

- **路由**。身份 = Nostr 公钥，relay 的 `#p` tag 过滤就是"找对方"的机制。
- **加密运输**。NIP-44 端到端加密，全程密文。
- **自动降级**。LAN 可达走毫秒直连，不可达自动走全球 relay 网络。

### 为什么不需要自己的服务器

Nostr 全球有几千个公共 relay。CipherPipe 启动时向所有 relay 开持久 WebSocket，消息即时推送。relay 之间不互相同步，靠客户端向多个 relay 同时发布保证到达。不依赖单一 relay——挂了一个，其他的继续跑。

## 架构

```
任何 client ──WS──→ Hub ──┬── LAN peer（毫秒）
                          └── Nostr relay（全球可达）
```

- **Hub** 是唯一中间层：路由、持久化、送达确认、消息状态。没有传统意义上的"服务器"。
- **Client** 是 thin client：只做输入/输出/显示。不处理路由、加密、协议。
- **消息协议统一**：所有 client 发相同的消息格式，收相同的消息格式。

## 项目结构

```
cipherpipe/
├── backend/                    # Hub 中间层
│   ├── hub/
│   │   ├── proxy.py           # WebSocket/HTTP 入口，消息路由核心
│   │   └── router.py          # PeerRouter — LAN/relay 路由策略
│   ├── core/
│   │   ├── config.py          # .env 配置加载
│   │   ├── crypto.py          # NIP-44 加解密 + BIP-340 签名
│   │   └── store.py           # SQLite 持久化（消息/联系人/状态）
│   ├── network/
│   │   ├── relay.py           # Nostr relay 连接池管理
│   │   └── lan.py             # mDNS LAN 节点发现
│   ├── file/
│   │   └── transfer.py        # 文件分片收发 + forward_file()
│   └── agent.py               # 对端 Agent（收消息/文件，可选自动回复）
├── frontend/                   # 客户端（thin client）
│   ├── web/
│   │   └── Dashboard.vue      # 浏览器 UI（Vue 3，零加密逻辑）
│   └── cli/
│       └── cli.py             # 终端聊天客户端
├── tests/
│   └── test_transfer.py       # 消息+文件传输测试（5/5）
├── data/                       # 运行时数据
│   ├── nostr.key              # Hub 身份私钥（自动生成）
│   ├── *.key                  # 各 client 身份私钥
│   ├── cipherpipe.db          # SQLite 数据库
│   ├── inbox.jsonl            # Agent 收件箱
│   ├── outbox.jsonl           # Agent 发件箱
│   └── downloads/             # 接收的文件
├── run.sh                      # 启动 Hub
├── cipherchat                  # 终端聊天快捷入口
├── .env                        # 环境变量
└── logs/                       # Hub 日志（JSONL）
```

## 快速开始

```bash
# 1. 启动 Hub
bash run.sh

# 2. 创建身份（CLI）
./cipherchat create          # 生成私钥，打印公钥

# 3. 终端聊天
./cipherchat <对方公钥>       # 输入对方公钥，开始聊天

# 4. 浏览器
open http://localhost:8700
# 点击"创建身份"，拿到公钥
# 把公钥发给对方，添加对方公钥，开始聊天

# 5. Agent（可选）
PYTHONPATH=. python3 backend/agent.py --keyfile data/claude.key
```

## 消息协议

**客户端 → Hub：**
```json
{"type": "msg", "text": "hello", "to": "<对方公钥>"}
{"type": "file", "name": "a.pdf", "size": 12345, "to": "<对方公钥>"}
<binary data>   ← 紧跟在 file header 后面的二进制帧
```

**Hub → 客户端：**
```json
{"type": "msg", "id": "...", "from": "<发件人>", "text": "hello", "delivered": true}
{"type": "file", "id": "...", "from": "<发件人>", "name": "a.pdf", "size": 12345}
```

所有中间逻辑（路由、持久化、送达确认、reaction、typing）由 Hub 统一处理。

## 已读/送达

- LAN 消息：Hub 转发即送达 → `delivered: true` → 发送方显示 `✓`（蓝色）
- Nostr 消息：发布到 relay → `delivered: false` → 发送方显示 `✓`（灰色）
- 客户端不处理已读逻辑，所有状态由 Hub 推送

## 文件传输

统一协议：`{type:'file', name, size, to}` + 二进制 WebSocket frame。

1. 客户端发送 JSON header + 原始文件数据（二进制帧）
2. Hub 接收 → 落盘 → 转发给对端（LAN 直传 / Nostr 分片）
3. Hub 通知收发双方

客户端零分片、零 base64、零协议知识。超 `CP_FILE_MAX_SIZE`（.env 可配，默认 100MB）直接拒绝。

## CLI 命令

```bash
./cipherchat create           # 生成/查看自己的公钥
./cipherchat show             # 显示已有公钥
./cipherchat <对方公钥>        # 开始聊天
./cipherchat                  # 交互式：输入对方公钥后聊天

聊天内命令：
  /send <文件路径>             发送文件
  /quit                       退出
```

## 加密

- 协议：NIP-44（XChaCha20-Poly1305）
- 密钥交换：ECDH（secp256k1）
- 签名：BIP-340 Schnorr
- 每条消息独立随机 nonce，防重放

## 配置

`.env` 可配项：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CP_PORT` | 8700 | Hub 端口 |
| `CP_RELAYS` | damus.io, nos.lol, nostr.band | Nostr relay 列表 |
| `CP_KEY_FILE` | nostr.key | Hub 身份私钥 |
| `CP_FILE_MAX_SIZE` | 104857600 (100MB) | 文件上传上限 |

## 开发原则

- **客户端只做 I/O**：消息收发和显示，不做路由/加密/状态管理
- **Hub 处理一切**：路由、持久化、送达确认、消息状态
- **零硬编码**：配置从 `.env` → config.py 统一加载
- **TDD**：先写测试 → 看测试失败 → 写代码 → 看测试通过

## 测试

```bash
pytest tests/ -v --asyncio-mode=auto
```

## 依赖

`websockets cryptography structlog coincurve zeroconf python-socks`
