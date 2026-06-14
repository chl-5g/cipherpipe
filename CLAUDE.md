# CipherPipe

端到端加密数据传输管道，基于 Nostr 协议。

## 架构

```
节点 = 前端(Dashboard/CLI) + Hub(proxy)
节点 ←──LAN/relay──→ 对端节点
```

- **每个节点 = 前端 + Hub**。前端只做 I/O，Hub 负责路由、加密、持久化
- **节点之间对等**，通过 LAN 直连或 Nostr relay 通信，没有中心服务器

## 项目结构

```
cipherpipe/
├── backend/
│   ├── hub/          proxy.py (入口) + router.py (PeerRouter)
│   ├── core/         config.py + crypto.py + store.py
│   ├── network/      relay.py + lan.py
│   ├── file/         transfer.py
│   └── agent.py      对端 agent
├── frontend/
│   ├── web/          Dashboard.vue (浏览器)
│   └── cli/          cli.py (终端)
├── run.sh            # 启动 Hub
├── cipherchat        # 终端聊天快捷入口
├── data/             # 运行时数据
└── logs/
```

## 原则

- **前端只做 I/O**：消息收发和显示，路由/加密/持久化一律不碰
- **Hub 处理一切**：路由、持久化、送达确认、消息状态
- **零硬编码**：配置从 `.env` → config.py 统一加载
- **单端口**：8700 承载 HTTP/WS/LAN peer/文件传输
- **TDD**：先写测试 → 看测试失败 → 写代码 → 看测试通过。不通过测试验证不做任何实现

## 启动

```bash
bash run.sh                                         # 启动 Hub
PYTHONPATH=. python3 backend/agent.py --keyfile data/claude.key  # 启动 agent
```

## 消息协议

节点 → Hub: `{type:'msg', text, to}` / `{type:'file', path, to}`
Hub → 节点: `{type:'msg', id, from, text, delivered}`

所有中间逻辑（已读、送达、reaction、typing）由 Hub 统一处理。

## 依赖

`websockets cryptography structlog coincurve zeroconf python-socks`
