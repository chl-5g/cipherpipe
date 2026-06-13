# CipherPipe

端到端加密数据传输管道，基于 Nostr 协议。本机 `~/cipherpipe/`（仅 Mac）。

## 项目结构

```
cipherpipe/
├── run.sh                  # 启动 proxy
├── .env                    # 环境变量
├── requirements.txt
├── src/
│   └── cipherpipe/         # Python 包
│       ├── proxy.py        # Nostr 桥 + 浏览器入口
│       ├── agent.py        # agent 客户端（LAN peer）
│       ├── cli.py          # CLI 人类客户端
│       ├── config.py       # 统一配置加载
│       ├── nostr_crypto.py # NIP-44 加解密 + 签名
│       ├── storage.py      # SQLite 持久化
│       ├── relay_manager.py
│       ├── file_handler.py # 文件分片收发
│       ├── lan_discovery.py
│       └── dashboard.html  # 浏览器 UI
├── data/                   # 运行时数据
│   ├── nostr.key           # proxy 身份私钥
│   ├── claude.key          # agent 身份私钥
│   ├── cipherpipe.db       # 消息/联系人存储
│   ├── inbox.jsonl         # agent 收件箱
│   ├── outbox.jsonl        # agent 发件箱
│   └── downloads/          # 接收的文件
├── logs/                   # proxy 日志（JSONL）
└── archive/                # 旧版文件
```

## 原则

- **零硬编码**：端口、relay 地址、文件路径全部从 `.env` 读取，由 `config.py` 统一加载
- **CipherPipe 只管管道**：加密传输、路由转发。不调 LLM API、不持 API key
- **单端口**：8700（可配）同时承载 HTTP/WS/LAN peer/文件传输
- **无 print**：所有输出走 structlog

## 启动

```bash
bash run.sh                                    # 启动 proxy
python3 src/cipherpipe/agent.py --keyfile data/claude.key  # 启动 agent
```

`run.sh` 自动 kill 旧进程后启动。agent 需单独起。

## 文件传输

浏览器发文件走分片上传（每片 256KB）：
`file_start` → N×`file_chunk` → `file_end`
proxy 拼装 → 转发分片给 peer → peer 拼装落盘到 `data/downloads/`

## agent 回复模式

| mode | 行为 |
|------|------|
| `none` | 默认，仅写 inbox.jsonl |
| `echo` | 自动回复 `[echo] <原文>` |
| `cmd:<命令>` | 消息 stdin 传入命令，stdout 作为回复 |

## 依赖

`websockets cryptography structlog coincurve zeroconf python-socks`
