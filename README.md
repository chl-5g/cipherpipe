# CipherPipe

端到端加密数据传输管道。基于 Nostr 协议，无需中心服务器。

人类浏览器、AI agent、外部脚本平等接入。

## 项目结构

```
src/cipherpipe/     # Python 包
├── proxy.py        # 核心：Nostr 桥 + 浏览器入口 + LAN 直连
├── agent.py        # Agent 客户端（LAN peer，收消息/文件）
├── cli.py          # 人类 CLI 客户端
├── config.py       # 统一配置（.env → 全局读取）
├── nostr_crypto.py # NIP-44 加解密 + BIP-340 Schnorr 签名
├── storage.py      # SQLite 持久化（消息、联系人、状态）
├── relay_manager.py# Relay 延迟排序与连接管理
├── file_handler.py # 文件分片收发
├── lan_discovery.py# 局域网服务发现
└── dashboard.html  # 浏览器聊天 UI（零加密逻辑）

data/               # 运行时数据
├── nostr.key       # Proxy 身份私钥
├── claude.key      # Agent 身份私钥
├── cipherpipe.db   # 消息/联系人存储
├── inbox.jsonl     # Agent 收件箱
├── outbox.jsonl    # Agent 发件箱
└── downloads/      # 接收的文件
```

## 快速开始

```bash
# 启动 proxy
bash run.sh

# 另开终端，启动 agent
python3 src/cipherpipe/agent.py --keyfile data/claude.key
```

浏览器打开 `http://localhost:8700`，添加联系人公钥即可。

## 设计哲学

CipherPipe 是一根管子。管子里流什么、谁在流，管子自己不知道。

三个约束：
1. **服务器零知识** — relay 只转发加密 blob，永不解密
2. **参与者平等** — 人类浏览器、AI agent、外部脚本，对 relay 来说都是两个公钥互发加密事件
3. **无单点故障** — 同时连多个 Nostr relay，挂一个自动切

## 三层传输

| 层 | 延迟 | 用途 |
|----|------|------|
| LAN WebSocket | <1ms | 同机/同局域网 agent 直连，不经过 relay |
| Nostr relay 池 | 实时推送 | 跨网络、跨地域。加密事件全球 relay 转发 |
| Browser proxy | <1ms | 浏览器 ↔ proxy 明文。密钥只存 proxy |

路由策略：先查 LAN_CLIENTS，命中走 LAN 毫秒级；未命中走 Nostr relay。

## 加密

- 协议：NIP-44（XChaCha20-Poly1305）
- 密钥交换：ECDH（secp256k1）
- 签名：BIP-340 Schnorr
- 每条消息独立随机 nonce

## Agent 模式

```bash
# 纯管道（默认），收消息写 inbox
python3 src/cipherpipe/agent.py --keyfile data/claude.key

# echo 测试模式
python3 src/cipherpipe/agent.py --keyfile data/claude.key --reply-mode echo

# 外部命令模式（消息 stdin 传入，stdout 作为回复）
python3 src/cipherpipe/agent.py --keyfile data/claude.key --reply-mode cmd:./my_ai.sh
```

## 文件传输

分片传输，不依赖 WebSocket 单帧大小限制：

`file_start` → N×`file_chunk`(256KB/片) → `file_end`

Proxy 转发分片到 peer，peer 拼装落盘 `data/downloads/`。

## 依赖

`websockets cryptography structlog coincurve zeroconf python-socks`
