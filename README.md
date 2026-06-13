# CipherPipe

端到端加密数据传输管道。基于 Nostr 协议，无需中心服务器。

## 核心理念

你的身份就是你的一对公私钥。谁有你的公钥谁就能给你发加密消息。人类、AI agent、外部系统平等接入。Nostr 全球 relay 网络替你转发——不需要自己维护服务器。

## 架构

```
Browser (纯聊天UI) ──plaintext WS──→ proxy.py ──NIP-44 encrypted──→ Nostr Relays (全球)
                                           ↕
                                      CLI/Agent (直连 Nostr)
```

### 两层分离

| 层 | 职责 |
|----|------|
| **proxy.py** | 持有 Nostr 密钥对。浏览器明文 ↔ NIP-44 加密的双向转换。连接多个 Nostr relay |
| **cli.py** | 独立 Nostr 客户端。持密钥对，直连 relay，人/Agent 共用 |
| **Nostr Relay** | 哑中继（公共基础设施）。转发加密事件，不解密 |

### 为什么不需要自己的服务器

Nostr 全球有几千个公共 relay。每次发布事件时连多个 relay，一个挂了自动切另一个。不依赖任何单一 relay，不需要维护 `server.py`，不存在单点故障。

### 加密模型

- **NIP-44**（XChaCha20-Poly1305）：Nostr 现代加密标准。ECDH 密钥交换 + HKDF 派生会话密钥
- 每个联系人（公钥对）之间独立加密
- 浏览器不碰密钥——proxy 持有密钥，浏览器只收发明文
- AI agent 持自己的密钥对，直连 Nostr relay

## 快速开始

```bash
pip install -r requirements.txt
python proxy.py
```

浏览器打开 `http://localhost:8701`。

或一键：`bash run.sh`

## 使用方式

### 浏览器

1. 打开 `http://localhost:8701`
2. 首次启动自动生成 Nostr 身份（公钥显示在底部）
3. 点 **Add Peer** → 输入对方的公钥
4. 开始聊天。所有消息 NIP-44 端到端加密

### CLI（人类或 AI Agent）

```bash
python cli.py --peer PEER_PUBKEY_HEX --name my_agent

# Agent 模式（只收不发）
python cli.py --peer PEER_PUBKEY_HEX --name agent_0.11 --no-stdin
```

## 安全模型

| 层级 | 知道什么 |
|------|---------|
| Nostr Relay | 只知道事件元数据（pubkey、时间戳）。不知道消息内容 |
| proxy.py | 持有本机私钥。加密后发给 relay，解密后传给浏览器 |
| Browser | 只看到明文。不持有密钥 |
| AI Agent | 持自己的密钥对。直连 relay，自行加解密 |

- **Nostr relay 零知识**：NIP-44 端到端加密，relay 永不见明文
- **多 relay 冗余**：连 3+ 个 relay，无单点故障

## 多用户部署

```
                      Nostr Relay 网络 (全球公共)
                    /        |        \        \
              proxy.py   proxy.py   cli.py   cli.py
              (机器A)    (机器B)    (Agent)  (手机)
              Browser    Browser
```

- **每台机器**运行一个 proxy.py，持有该机器的 Nostr 密钥对
- **每个 CLI/Agent** 持自己的密钥对
- 对等方通过公钥互相发现和通信
- 无需共享房间密钥——密钥交换通过 ECDH 自动完成

## 项目结构

```
cipherpipe/
  proxy.py          # Nostr 客户端桥 (8701)
  cli.py            # Nostr CLI 客户端
  dashboard.html    # 浏览器聊天 UI（纯 UI，零加密）
  run.sh            # 一键启动
  nostr.key         # Nostr 私钥（自动生成，勿泄露）
  logs/             # 日志
  archive/          # 旧版 server.py/db.py/crypto_room.py（已弃用）
```
